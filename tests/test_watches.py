"""Bibliothèque et enrichissement : preuves persistantes, aucune API externe."""
import asyncio
import copy
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.agent.engine import Engine
from app.agent.web import ToolFailure
from app.main import create_app
from app.schemas import MissionInput, SaveInput
from app.storage import Store


TOKEN = 'watch-review-fixture-' + 'x' * 32
AUTH = {'Authorization': 'Bearer ' + TOKEN}
REQUEST = {
    'subject': 'Nouveautés PostgreSQL', 'domains': ['example.com'],
    'action_budget': 10, 'duration_minutes': 1,
}
QUOTE = 'Une nouveauté documentée et vérifiable.'
PAGE = {
    'source_id': 'source-a', 'url': 'https://example.com/news',
    'title': 'Publication de test', 'text': QUOTE,
    'retrieved_at': '2026-09-08T12:00:00+00:00', 'published_at': None,
    'status': 'ok', 'error': None,
}


class NeverCalled:
    async def decide(self, context):
        pytest.fail('La consultation, le cache et la confirmation ne lancent pas le modèle dans ces tests.')


class FixtureReader:
    """Résultat de lecture contrôlé, sans réseau."""
    def __init__(self, page=None):
        self.page = copy.deepcopy(page or PAGE)
        self.calls = []

    async def read(self, url, domains):
        self.calls.append((url, list(domains)))
        return copy.deepcopy(self.page)


@pytest.fixture
def store(tmp_path):
    value = Store(str(tmp_path / 'watch.db'))
    try:
        yield value
    finally:
        value.db.close()


def new_run(store, **changes):
    return store.create(MissionInput(**{**REQUEST, **changes}))


def draft(summary='La version initiale est publiée.', *, key='finding-a',
          change='new', related=None, source_id='source-a', quote=QUOTE):
    return SaveInput.model_validate({
        'finding': {
            'title': 'Publication PostgreSQL', 'summary': summary,
            'developer_impact': 'À examiner dans un environnement de test.',
            'evidence': [{'source_id': source_id, 'quote': quote}],
        },
        'idempotency_key': key, 'change': change, 'related_finding_id': related,
    })


def read_page(store, mid, page=None):
    engine = Engine(store, NeverCalled())
    reader = FixtureReader(page)
    asyncio.run(engine.execute(mid, 'read_page', {'url': reader.page['url']}, reader))
    assert len(reader.calls) == 1
    return engine


def completed_with_finding(store, **changes):
    mid = new_run(store, **changes)
    read_page(store, mid).save_finding(mid, draft())
    store.finish(mid, 'completed')
    return mid, store.watch_id_for(mid)


def test_legacy_migration_groups_oldest_without_rewriting_snapshots_or_events(tmp_path):
    path = tmp_path / 'legacy.db'
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE missions (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
    db.execute('CREATE TABLE events (mission_id TEXT, seq INTEGER, at TEXT, kind TEXT, data TEXT, PRIMARY KEY(mission_id,seq))')
    for mid, epoch, domains, budget in [
        ('oldest', 100, ['example.com'], 3),
        ('newer', 200, ['example.com'], 20),
        ('other-scope', 300, ['other.org'], 3),
    ]:
        data = dict(REQUEST, id=mid, domains=domains, action_budget=budget,
                    status='completed', created_at=f'2026-09-0{epoch // 100}T12:00:00+00:00',
                    started_epoch=epoch, ended_epoch=epoch + 1, ended_at='2026-09-08T12:00:00+00:00',
                    sources=[], findings=[], pages={}, keys={}, attempts={},
                    actions_used=0, model_calls_used=0, network_requests_used=0,
                    current_action=None, error=None, had_errors=False)
        db.execute('INSERT INTO missions VALUES (?,?)', (mid, json.dumps(data, ensure_ascii=False)))
        db.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                   (mid, 1, data['created_at'], 'created', '{"preuve":"à conserver exactement"}'))
    db.commit()
    before_missions = db.execute('SELECT * FROM missions ORDER BY id').fetchall()
    before_events = db.execute('SELECT * FROM events ORDER BY mission_id,seq').fetchall()
    db.close()
    for _ in range(2):
        migrated = Store(str(path))
        try:
            assert migrated.watch_id_for('oldest') == migrated.watch_id_for('newer') == 'oldest'
            assert migrated.watch_id_for('other-scope') == 'other-scope'
            assert migrated.list_watches()['total'] == 2
            assert migrated.db.execute('SELECT * FROM missions ORDER BY id').fetchall() == before_missions
            assert migrated.db.execute('SELECT * FROM events ORDER BY mission_id,seq').fetchall() == before_events
        finally:
            migrated.db.close()


def test_library_requires_auth_and_paginates_without_model_calls(tmp_path):
    app = create_app(db_path=str(tmp_path / 'db'), access_token=TOKEN, provider=NeverCalled())
    with TestClient(app) as client:
        store = app.state.store
        mid, wid = completed_with_finding(store)
        other = new_run(store, subject='Nouveautés Rust')
        store.finish(other, 'completed')
        before = store.events(mid)
        for path in ['/api/watches', '/api/watches/' + wid, '/api/watches/introuvable']:
            assert client.get(path).status_code == 401
            assert client.get(path, headers={'Authorization': 'Bearer mauvais'}).status_code == 401
        first = client.get('/api/watches?limit=1', headers=AUTH).json()
        second = client.get('/api/watches?limit=1&offset=1', headers=AUTH).json()
        assert first['total'] == second['total'] == 2
        assert len(first['watches']) == len(second['watches']) == 1
        assert first['watches'][0]['id'] != second['watches'][0]['id']
        assert 'findings' not in first['watches'][0]
        filtered = client.get('/api/watches?query=POSTGRESQL', headers=AUTH).json()
        assert [w['id'] for w in filtered['watches']] == [wid]
        detail = client.get('/api/watches/' + wid, headers=AUTH).json()
        assert detail['runs'][0]['id'] == mid
        assert detail['findings'][0]['source_links'][0]['url'] == PAGE['url']
        assert client.get('/api/watches/introuvable', headers=AUTH).status_code == 404
        assert client.get('/api/watches?limit=101', headers=AUTH).status_code == 422
        assert client.get('/api/watches?offset=-1', headers=AUTH).status_code == 422
        assert store.events(mid) == before


def test_similar_subject_requires_confirmation_before_creating_run(tmp_path):
    app = create_app(db_path=str(tmp_path / 'db'), access_token=TOKEN, provider=NeverCalled())
    with TestClient(app) as client:
        mid, wid = completed_with_finding(app.state.store)
        before = app.state.store.get(mid), app.state.store.events(mid)
        launched = []
        app.state.engine.launch = launched.append
        request = {**REQUEST, 'subject': 'Dernières nouveautés PostgreSQL'}
        response = client.post('/api/missions', headers=AUTH, json=request)
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'similar_watches'
        assert response.json()['detail']['candidates'][0]['id'] == wid
        assert launched == []
        assert app.state.store.watch(wid)['run_count'] == 1
        confirmed = client.post('/api/missions', headers=AUTH, json={**request, 'watch_id': wid})
        assert confirmed.status_code == 202
        assert confirmed.json()['watch_id'] == wid
        assert confirmed.json()['id'] != mid
        assert launched == [confirmed.json()['id']]
        assert app.state.store.watch(wid)['run_count'] == 2
        assert (app.state.store.get(mid), app.state.store.events(mid)) == before


def test_changed_domains_are_not_silently_merged_or_reinjected(tmp_path):
    app = create_app(db_path=str(tmp_path / 'db'), access_token=TOKEN, provider=NeverCalled())
    with TestClient(app) as client:
        _, wid = completed_with_finding(app.state.store)
        app.state.engine.launch = lambda mid: None
        request = {**REQUEST, 'domains': ['other.org']}
        pending = client.post('/api/missions', headers=AUTH, json=request)
        assert pending.status_code == 409
        assert app.state.store.watch(wid)['run_count'] == 1
        confirmed = client.post('/api/missions', headers=AUTH, json={**request, 'watch_id': wid})
        assert confirmed.status_code == 202
        state = app.state.store.get(confirmed.json()['id'])
        assert state['domains'] == ['other.org']
        assert state['known_findings'] == []
        assert state['pages'] == {} and state['sources'] == []


def test_explicit_new_choice_keeps_similar_watches_separate(tmp_path):
    app = create_app(db_path=str(tmp_path / 'db'), access_token=TOKEN, provider=NeverCalled())
    with TestClient(app) as client:
        _, old = completed_with_finding(app.state.store)
        app.state.engine.launch = lambda mid: None
        request = {**REQUEST, 'subject': 'Dernières nouveautés PostgreSQL', 'allow_new': True}
        response = client.post('/api/missions', headers=AUTH, json=request)
        assert response.status_code == 202
        assert response.json()['watch_id'] != old
        assert app.state.store.list_watches()['total'] == 2
        assert response.json().get('known_findings', []) == []


def test_cache_and_forced_refresh_keep_one_watch_and_immutable_old_run(tmp_path):
    app = create_app(db_path=str(tmp_path / 'db'), access_token=TOKEN, provider=NeverCalled())
    with TestClient(app) as client:
        old, wid = completed_with_finding(app.state.store)
        before = app.state.store.get(old), app.state.store.events(old)
        launched = []
        app.state.engine.launch = launched.append
        cached = client.post('/api/missions', headers=AUTH, json=REQUEST)
        assert cached.status_code == 200 and cached.json()['id'] == old
        assert cached.json()['reuse']['reason'] == 'recent_completed'
        assert launched == []
        fresh_request = {**REQUEST, 'watch_id': wid, 'force_refresh': True}
        fresh = client.post('/api/missions', headers=AUTH, json=fresh_request)
        assert fresh.status_code == 202
        state = fresh.json()
        assert state['id'] != old and state['watch_id'] == wid
        assert state['actions_used'] == state['model_calls_used'] == 0
        assert state['known_findings'][0]['entry_id'].startswith(old + ':')
        assert state['elapsed_seconds'] == 0
        repeat = client.post('/api/missions', headers=AUTH, json=fresh_request)
        assert repeat.status_code == 200 and repeat.json()['id'] == state['id']
        assert repeat.json()['reuse']['reason'] == 'already_running'
        assert launched == [state['id']]
        assert app.state.store.watch(wid)['run_count'] == 2
        assert (app.state.store.get(old), app.state.store.events(old)) == before


def test_refresh_with_different_budget_updates_same_watch_without_cache(store):
    old, wid = completed_with_finding(store)
    request = MissionInput(**{**REQUEST, 'action_budget': 20})
    assert store.reusable(request) is None
    fresh = store.create(request)
    assert fresh != old and store.watch_id_for(fresh) == wid
    assert store.get(fresh)['action_budget'] == 20
    assert store.get(old)['action_budget'] == 10


def test_auto_mode_keeps_identity_after_domains_have_been_selected(store):
    request = MissionInput(subject=REQUEST['subject'], auto_sources=True)
    mid = store.create(request)
    state = store.get(mid)
    state['domains'] = ['example.com', 'other.org']
    store.save(state, 'sources_selected', {})
    store.finish(mid, 'completed')
    assert store.reusable(request) == mid
    assert store.exact_watch(request) == store.watch_id_for(mid)
    manual = MissionInput(subject=REQUEST['subject'], domains=state['domains'])
    assert store.reusable(manual) is None
    assert store.exact_watch(manual) is None


def test_new_update_and_duplicate_preserve_versions_and_references(store):
    old, wid = completed_with_finding(store)
    old_data, old_events = store.get(old), store.events(old)
    first_entry = store.watch(wid)['findings'][0]['entry_id']
    update = new_run(store, force_refresh=True)
    changed_page = {**PAGE, 'text': 'La nouvelle version corrige une régression.'}
    engine = read_page(store, update, changed_page)
    args = draft('La publication est corrigée.', key='update-a', change='update',
                 related=first_entry, quote=changed_page['text'])
    result = engine.save_finding(update, args)
    assert result['disposition'] == 'updated'
    assert engine.save_finding(update, args)['disposition'] == 'already_saved'
    store.finish(update, 'completed')
    watch = store.watch(wid)
    assert watch['findings_count'] == 1
    assert watch['findings'][0]['previous_versions'] == [first_entry]
    assert watch['findings'][0]['mission_id'] == update
    assert watch['runs'][0]['updated_findings_count'] == 1
    assert watch['runs'][0]['new_findings_count'] == 0
    second_entry = watch['findings'][0]['entry_id']
    repeated = new_run(store, force_refresh=True)
    repeated_engine = read_page(store, repeated, changed_page)
    duplicate = repeated_engine.save_finding(repeated, draft(
        'La publication est corrigée.', key='repeat-a', quote=changed_page['text']))
    # Une répétition identique est reconnue même si le modèle annonce « new ».
    assert duplicate['disposition'] == 'already_known'
    assert duplicate['related_finding_id'] == second_entry
    assert store.get(repeated)['findings'] == []
    assert any(e['kind'] == 'finding_unchanged' for e in store.events(repeated))
    assert store.watch(wid)['findings_count'] == 1
    assert (store.get(old), store.events(old)) == (old_data, old_events)


def test_old_evidence_must_be_read_again_before_update(store):
    old, wid = completed_with_finding(store)
    entry = store.watch(wid)['findings'][0]['entry_id']
    fresh = new_run(store, force_refresh=True)
    assert store.get(fresh)['known_findings'][0]['entry_id'] == entry
    assert store.get(fresh)['pages'] == {}
    engine = Engine(store, NeverCalled())
    args = draft('Correction vérifiée.', change='update', related=entry)
    with pytest.raises(ToolFailure, match='invalid_evidence'):
        engine.save_finding(fresh, args)
    assert store.get(fresh)['findings'] == []
    read_page(store, fresh)
    assert engine.save_finding(fresh, args)['disposition'] == 'updated'
    assert store.get(old)['findings'][0]['summary'] == 'La version initiale est publiée.'


@pytest.mark.parametrize('change', ['update', 'duplicate'])
def test_unknown_reference_is_rejected_even_with_valid_new_evidence(store, change):
    _, wid = completed_with_finding(store)
    fresh = new_run(store, force_refresh=True)
    engine = read_page(store, fresh)
    with pytest.raises(ToolFailure, match='unknown_related_finding'):
        engine.save_finding(fresh, draft('Autre affirmation.', change=change, related='foreign:unrelated'))
    assert store.get(fresh)['findings'] == []
    assert store.watch(wid)['findings_count'] == 1


def test_stale_update_cannot_create_a_second_version_as_new_finding(store):
    _, wid = completed_with_finding(store)
    entry = store.watch(wid)['findings'][0]['entry_id']
    fresh = new_run(store, force_refresh=True)
    engine = read_page(store, fresh)
    first = draft('Première correction.', key='update-one', change='update', related=entry)
    engine.save_finding(fresh, first)
    assert engine.save_finding(fresh, first)['disposition'] == 'already_saved'
    with pytest.raises(ToolFailure, match='related_finding_superseded'):
        engine.save_finding(fresh, draft('Deuxième correction.', key='update-two', change='update', related=entry))
    assert store.watch(wid)['findings_count'] == 1


def test_explicit_retraction_can_restore_historical_content_as_a_new_version(store):
    _, wid = completed_with_finding(store)
    original = store.watch(wid)['findings'][0]['entry_id']
    second = new_run(store, force_refresh=True)
    read_page(store, second).save_finding(second, draft(
        'Une correction différente.', key='changed', change='update', related=original))
    store.finish(second, 'completed')
    corrected = store.watch(wid)['findings'][0]['entry_id']
    third = new_run(store, force_refresh=True)
    result = read_page(store, third).save_finding(third, draft(
        key='retraction', change='update', related=corrected))
    assert result['disposition'] == 'updated'
    store.finish(third, 'completed')
    watch = store.watch(wid)
    assert watch['findings_count'] == 1
    assert watch['findings'][0]['mission_id'] == third
    assert watch['findings'][0]['summary'] == 'La version initiale est publiée.'
    assert watch['findings'][0]['previous_versions'] == [original, corrected]
    assert watch['runs'][0]['updated_findings_count'] == 1


def test_context_is_bounded_and_excludes_full_pages_and_other_domains(store):
    mid = new_run(store)
    state = store.get(mid)
    state['sources'] = [{k: v for k, v in PAGE.items() if k != 'text'}]
    state['pages'] = {'source-a': {**PAGE, 'text': 'NE PAS REINJECTER ' * 2000}}
    state['findings'] = [
        dict(draft('Constat %02d ' % i + 'x' * 1900).finding.model_dump(), finding_id=f'finding-{i}')
        for i in range(60)
    ]
    store.save(state, 'fixture_seed', {})
    store.finish(mid, 'completed')
    context = store.prior_context(store.watch_id_for(mid), ['example.com'])
    assert 1 <= len(context['known_findings']) <= 20
    assert context['known_findings_truncated'] is True
    assert sum(len(json.dumps(f, ensure_ascii=False)) for f in context['known_findings']) <= 12000
    assert all(len(f['summary']) <= 400 for f in context['known_findings'])
    assert 'NE PAS REINJECTER' not in json.dumps(context)
    assert all('evidence' not in f and 'quote' not in f for f in context['known_findings'])
    excluded = store.prior_context(store.watch_id_for(mid), ['other.org'])
    assert excluded['known_findings'] == []


def test_partial_completed_run_does_not_advance_update_since(store):
    old, wid = completed_with_finding(store)
    baseline = store.get(old)['ended_at']
    later = new_run(store, force_refresh=True)
    state = store.get(later)
    state['had_errors'] = True
    store.save(state, 'tool_error', {'code': 'timeout'})
    store.finish(later, 'completed')
    assert store.snapshot(later)['summary']['partial'] is True
    assert store.prior_context(wid, REQUEST['domains'])['update_since'] == baseline


def test_missing_or_foreign_watch_id_does_not_create_any_run(tmp_path):
    app = create_app(db_path=str(tmp_path / 'db'), access_token=TOKEN, provider=NeverCalled())
    with TestClient(app) as client:
        _, wid = completed_with_finding(app.state.store)
        for headers in [{}, {'Authorization': 'Bearer mauvais'}]:
            response = client.post('/api/missions', headers=headers,
                                   json={**REQUEST, 'watch_id': wid, 'force_refresh': True})
            assert response.status_code == 401
        response = client.post('/api/missions', headers=AUTH,
                               json={**REQUEST, 'watch_id': 'absent', 'force_refresh': True})
        assert response.status_code == 404
        assert app.state.store.watch(wid)['run_count'] == 1
