"""Offline adversarial fixtures; these do not prove live model compliance."""
import pytest
from app.agent.engine import Engine, Halt
from app.agent.web import ToolFailure
from app.schemas import MissionInput, SaveInput
from app.storage import Store


@pytest.fixture
def mission(tmp_path):
    store = Store(tmp_path / 'db')
    mid = store.create(MissionInput(subject='Veille agents', domains=['example.com']))
    yield store, mid
    store.db.close()


def save(store, mid, hosts, confidence='corroborated', identical=False, forged=False):
    data = store.get(mid)
    evidence = []
    for i, host in enumerate(hosts):
        text = 'Une annonce documentée numéro ' + str(0 if identical else i)
        data['pages'][str(i)] = {'url': f'https://{host}/news/{i}', 'text': text}
        evidence.append({'source_id': str(i), 'quote': 'Une citation inventée' if forged else text})
    store.save(data, 'fixture', {})
    Engine(store, object()).save_finding(mid, SaveInput(idempotency_key='one', finding={
        'title': 'Annonce', 'summary': 'Une annonce est documentée.',
        'developer_impact': 'Vérifier son applicabilité.', 'confidence': confidence,
        'event_date': '2026-09-08', 'date_status': 'in_window', 'evidence': evidence}))
    return store.snapshot(mid)['findings'][0]


@pytest.mark.parametrize('hosts,identical', [
    (['example.com', 'example.com'], False),
    (['example.com', 'www.example.com'], False),
    (['example.com', 'other.org'], True),
])
def test_corroboration_cannot_be_obtained_by_repeating_pages(mission, hosts, identical):
    f = save(*mission, hosts, identical=identical)
    assert f['confidence'] == 'single_source'
    assert 'indépendante' in f['caveats'][0]


def test_disagreement_is_not_silently_erased(mission):
    assert save(*mission, ['example.com'], confidence='conflicting')['confidence'] == 'conflicting'


def test_unverified_date_stays_unknown(mission):
    f = save(*mission, ['example.com'])
    assert f['event_date'] is None and f['date_status'] == 'unknown'


def test_fabricated_quote_never_enters_summary(mission):
    store, mid = mission
    with pytest.raises(ToolFailure, match='invalid_evidence'):
        save(store, mid, ['example.com'], forged=True)
    assert store.snapshot(mid)['findings'] == []


def report(store, mid, usage):
    data = store.get(mid)
    data['model_calls_used'] += 1
    store.save(data, 'model_started', {})
    if usage is not None:
        store.save(data, 'model_finished', {'usage': usage})


def test_usage_aggregates_all_calls_and_cache_without_double_counting(mission):
    store, mid = mission
    report(store, mid, {'input_tokens': 10, 'output_tokens': 3, 'cache_read_input_tokens': 20})
    report(store, mid, {'input_tokens': 5, 'output_tokens': 2, 'cache_creation_input_tokens': 30})
    store.finish(mid, 'completed')
    first = store.snapshot(mid)['usage']
    assert first['total_tokens'] == 70 and first['tokens_complete']
    assert first['model_calls'] == first['measured_calls'] == 2
    assert store.snapshot(mid)['usage'] == first


@pytest.mark.parametrize('bad', [None, {}, {'input_tokens': -1, 'output_tokens': 2},
                                   {'input_tokens': True, 'output_tokens': 2}])
def test_missing_or_invalid_usage_is_not_reported_as_zero(mission, bad):
    store, mid = mission
    report(store, mid, {'input_tokens': 10, 'output_tokens': 2})
    report(store, mid, bad)
    usage = store.snapshot(mid)['usage']
    assert usage['tokens'] is None and usage['total_tokens'] is None
    assert not usage['tokens_complete'] and usage['unmeasured_calls'] == 1
    assert usage['observed_tokens']['input_tokens'] == 10


def test_zero_calls_is_a_measured_zero(mission):
    usage = mission[0].snapshot(mission[1])['usage']
    assert usage['tokens_complete'] and usage['total_tokens'] == 0


def test_token_threshold_prevents_next_model_reservation(mission):
    store, mid = mission
    report(store, mid, {'input_tokens': 24000, 'output_tokens': 10})
    before = store.get(mid)['model_calls_used']
    with pytest.raises(Halt) as stopped:
        Engine(store, object()).reserve(mid, 'model_calls_used', 60, 'model_started')
    assert stopped.value.status == 'budget_exhausted'
    assert store.get(mid)['model_calls_used'] == before
    assert store.events(mid)[-1]['kind'] == 'token_budget_exhausted'


@pytest.mark.parametrize('actions,limit', [(10,16000),(20,24000),(100,40000)])
def test_packs_have_explicit_token_limits(tmp_path, actions, limit):
    store = Store(tmp_path/'limits')
    try:
        mid = store.create(MissionInput(subject='Veille', domains=['example.com'], action_budget=actions))
        assert store.snapshot(mid)['usage']['token_budget'] == limit
    finally:
        store.db.close()
