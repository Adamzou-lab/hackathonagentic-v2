"""Pannes SQLite et récupération : aucun service ni modèle externe."""
import json
import os
import sqlite3
import time
import traceback

import pytest

from app.schemas import MissionInput
from app.storage import Store, StorageUnavailable


REQUEST = MissionInput(subject='Veille de test', domains=['example.com'])


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'data' / 'lockin.db'
    incidents = tmp_path / 'logs' / 'storage-incidents.jsonl'
    store = Store(path, incident_path=incidents)
    try:
        yield store, path, incidents
    finally:
        store.db.close()


def seed_inflight(store):
    mid = store.create(REQUEST)
    state = store.get(mid)
    state.update(status='running', actions_used=1, current_action='read_page',
                 current_operation={'id': 'op-read-1', 'dependency': 'web',
                                    'operation': 'read_page', 'started_at': state['created_at']})
    store.save(state, 'action_started', {'tool': 'read_page', 'action_number': 1})
    store.save(state, 'operation_started', dict(state['current_operation']))
    store.save(state, 'heartbeat', {'status': 'running'})
    return mid


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_recovery_records_last_seen_without_guessing_interruption_time(database):
    store, path, incidents = database
    mid = seed_inflight(store)
    prefix = store.events(mid)
    last_seen = prefix[-1]['at']
    assert store.get(mid)['last_seen_at'] == last_seen
    store.db.close()
    reopened = Store(path, incident_path=incidents)
    try:
        reopened.recover()
        state, events = reopened.get(mid), reopened.events(mid)
        assert state['status'] == 'failed' and state['error'] == 'process_interrupted'
        assert state['current_action'] is None and state['current_operation'] is None
        assert events[:len(prefix)] == prefix
        recovery = [event for event in events if event['kind'] == 'recovery_detected']
        assert len(recovery) == 1
        assert recovery[0]['data'] == {'last_seen_at': last_seen, 'interrupted_at': None, 'reaction': 'stop'}
        assert recovery[0]['at'] >= last_seen
        closed_operation = [event for event in events if event['kind'] == 'operation_finished']
        assert closed_operation[0]['data'] == {
            'operation_id': 'op-read-1', 'dependency': 'web', 'operation': 'read_page',
            'outcome': 'unknown', 'code': 'interrupted',
        }
        closed_action = [event for event in events if event['kind'] == 'action_finished']
        assert closed_action[0]['data']['result'] == {'status': 'unknown', 'error': 'interrupted'}
        assert events[-1]['kind'] == 'finished'
        assert state['last_seen_at'] == events[-1]['at']
        assert state['actions_used'] == 1
        reopened.recover()
        reopened.finish(mid, 'failed')
        assert reopened.events(mid) == events
    finally:
        reopened.db.close()


def test_recovery_of_legacy_snapshot_uses_last_event_without_heartbeat(database):
    store, _, _ = database
    mid = store.create(REQUEST)
    state = store.get(mid)
    state.pop('last_seen_at')
    state.pop('current_operation')
    store.db.execute('UPDATE missions SET data=? WHERE id=?', (json.dumps(state), mid))
    store.db.commit()
    last_seen = store.events(mid)[-1]['at']
    store.recover()
    recovery = next(event for event in store.events(mid) if event['kind'] == 'recovery_detected')
    assert recovery['data']['last_seen_at'] == last_seen
    assert recovery['data']['interrupted_at'] is None
    assert store.get(mid)['status'] == 'failed'


def test_interrupted_recovery_keeps_original_last_activity_time(database, monkeypatch):
    store, path, incidents = database
    mid = seed_inflight(store)
    last_activity = store.events(mid)[-1]['at']

    def interrupt_before_finish(*args, **kwargs):
        raise RuntimeError('fixture interruption during recovery')

    monkeypatch.setattr(store, 'finish', interrupt_before_finish)
    with pytest.raises(RuntimeError, match='fixture interruption'):
        store.recover()
    first_detection = store.events(mid)[-1]
    assert first_detection['kind'] == 'recovery_detected'
    assert first_detection['data']['last_seen_at'] == last_activity
    assert store.get(mid)['status'] == 'running'
    store.db.close()
    reopened = Store(path, incident_path=incidents)
    try:
        reopened.recover()
        detections = [event for event in reopened.events(mid) if event['kind'] == 'recovery_detected']
        assert len(detections) == 2
        assert [event['data']['last_seen_at'] for event in detections] == [last_activity, last_activity]
        assert detections[1]['at'] >= detections[0]['at']
        assert reopened.get(mid)['status'] == 'failed'
        assert reopened.get(mid)['recovery_last_seen_at'] == last_activity
        assert all(event['data']['interrupted_at'] is None for event in detections)
    finally:
        reopened.db.close()


def test_finish_closes_pending_entries_once_without_claiming_success(database):
    store, _, _ = database
    mid = seed_inflight(store)
    store.finish(mid, 'deadline_reached')
    events = store.events(mid)
    assert [event['kind'] for event in events[-3:]] == ['operation_finished', 'action_finished', 'finished']
    assert events[-3]['data']['outcome'] == 'unknown'
    assert events[-2]['data']['result']['status'] == 'unknown'
    assert store.snapshot(mid)['summary']['partial'] is True
    store.finish(mid, 'stopped')
    assert store.events(mid) == events
    assert store.get(mid)['status'] == 'deadline_reached'


def test_finish_does_not_duplicate_already_closed_operation_and_action(database):
    store, _, _ = database
    mid = seed_inflight(store)
    state = store.get(mid)
    state['current_operation'] = None
    store.save(state, 'operation_finished', {'operation_id': 'op-read-1', 'outcome': 'cancelled', 'code': 'cancelled'})
    state['current_action'] = None
    store.save(state, 'action_finished', {'tool': 'read_page', 'result': {'error': 'cancelled'}})
    store.finish(mid, 'stopped')
    events = store.events(mid)
    assert sum(event['kind'] == 'operation_finished' for event in events) == 1
    assert sum(event['kind'] == 'action_finished' for event in events) == 1


@pytest.mark.parametrize('operation', ['get', 'save', 'events', 'watch', 'check_available'])
def test_deleted_database_is_not_used_through_open_connection(database, operation):
    store, path, incident_path = database
    mid = store.create(REQUEST)
    state = store.get(mid)
    path.unlink()
    call = {
        'get': lambda: store.get(mid),
        'save': lambda: store.save(state, 'heartbeat', {'status': 'pending'}),
        'events': lambda: store.events(mid),
        'watch': lambda: store.watch(store.watch_id_for(mid)),
        'check_available': store.check_available,
    }[operation]
    with pytest.raises(StorageUnavailable, match='storage_file_missing'):
        call()
    assert store.unavailable is True
    failure = records(incident_path)
    assert len(failure) == 1
    assert failure[0]['kind'] == 'dependency_failed'
    assert failure[0]['data']['dependency'] == 'sqlite'
    assert failure[0]['data']['reaction'] == 'stop'
    assert failure[0]['data']['code'] == 'storage_file_missing'
    if operation in {'get', 'save', 'events'}:
        assert failure[0]['mission_id'] == mid
    with pytest.raises(StorageUnavailable):
        store.check_available()
    assert len(records(incident_path)) == 1
    assert not path.exists()


def test_replacement_is_detected_and_failure_stays_latched(database):
    store, path, incident_path = database
    mid = store.create(REQUEST)
    replacement = path.with_name('replacement.db')
    replacement.write_bytes(b'fixture replacement')
    os.replace(replacement, path)
    with pytest.raises(StorageUnavailable, match='storage_file_replaced'):
        store.get(mid)
    assert records(incident_path)[0]['data']['code'] == 'storage_file_replaced'
    assert path.read_bytes() == b'fixture replacement'
    with pytest.raises(StorageUnavailable, match='storage_file_replaced'):
        store.db.execute('SELECT 1')
    assert len(records(incident_path)) == 1


@pytest.mark.parametrize('replacement', [False, True])
def test_identity_marker_prevents_empty_recreation_on_restart(database, replacement):
    store, path, incident_path = database
    store.create(REQUEST)
    marker = store.db.identity_path
    assert marker.exists()
    store.db.close()
    if replacement:
        other = path.with_name('new.db')
        other.write_bytes(b'replacement fixture')
        os.replace(other, path)
    else:
        path.unlink()
    with pytest.raises(StorageUnavailable, match='storage_file_replaced' if replacement else 'storage_file_missing'):
        Store(path, incident_path=incident_path)
    assert path.exists() is replacement
    assert marker.exists()


def test_sqlite_error_rolls_back_snapshot_and_hides_exception_content(database):
    store, path, incident_path = database
    mid = store.create(REQUEST)
    before = store.get(mid)
    events_before = store.events(mid)
    secret = 'do-not-expose-fixture-api-secret'
    store.db.execute("CREATE TRIGGER refuse_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'do-not-expose-fixture-api-secret'); END")
    store.db.commit()
    changed = store.get(mid)
    changed['status'] = 'running'
    with pytest.raises(StorageUnavailable) as caught:
        store.save(changed, 'started', {})
    assert caught.value.code == 'storage_sqlite_error'
    assert secret not in ''.join(traceback.format_exception(caught.value))
    assert secret not in incident_path.read_text()
    assert records(incident_path)[0]['mission_id'] == mid
    assert store.unavailable is True
    raw = sqlite3.connect(path)
    try:
        assert json.loads(raw.execute('SELECT data FROM missions WHERE id=?', (mid,)).fetchone()[0]) == before
        assert raw.execute('SELECT COUNT(*) FROM events WHERE mission_id=?', (mid,)).fetchone()[0] == len(events_before)
    finally:
        raw.close()


def test_corrupt_database_startup_emits_only_structured_sanitized_error(tmp_path):
    path = tmp_path / 'corrupt.db'
    incidents = tmp_path / 'incidents.jsonl'
    path.write_bytes(b'not a database with fixture-private-content')
    with pytest.raises(StorageUnavailable) as caught:
        Store(path, incident_path=incidents)
    assert caught.value.code == 'storage_sqlite_error'
    assert 'fixture-private-content' not in incidents.read_text()
    assert records(incidents)[0]['data']['reaction'] == 'stop'


def test_unwritable_emergency_log_falls_back_to_structured_stderr(database, capsys):
    store, path, _ = database
    store.create(REQUEST)
    # Un dossier à la place du fichier de log donne une panne portable, même root.
    store.db.incident_log.path = path.parent
    path.unlink()
    with pytest.raises(StorageUnavailable):
        store.check_available()
    record = json.loads(capsys.readouterr().err)
    assert record['kind'] == 'dependency_failed' and record['delivery'] == 'stderr'
    assert record['data']['code'] == 'storage_file_missing'
    assert record['data']['reaction'] == 'stop'
    assert 'Traceback' not in json.dumps(record)


def test_cursor_fetch_cannot_continue_after_file_disappears(database):
    store, path, _ = database
    store.create(REQUEST)
    cursor = store.db.execute('SELECT data FROM missions')
    path.unlink()
    with pytest.raises(StorageUnavailable, match='storage_file_missing'):
        cursor.fetchone()


def test_heartbeat_persists_last_seen_in_same_transaction_as_event(database):
    store, _, _ = database
    mid = store.create(REQUEST)
    state = store.get(mid)
    store.save(state, 'heartbeat', {'status': state['status']})
    last = store.events(mid)[-1]
    assert last['kind'] == 'heartbeat'
    assert store.get(mid)['last_seen_at'] == last['at']


@pytest.mark.parametrize('table', ['missions', 'events'])
def test_corrupt_json_never_escapes_as_raw_decoder_error(database, table):
    store, _, incident_path = database
    mid = store.create(REQUEST)
    selector = 'id' if table == 'missions' else 'mission_id'
    store.db.execute(f'UPDATE {table} SET data=? WHERE {selector}=?', ('{"fixture-private-content":', mid))
    store.db.commit()
    with pytest.raises(StorageUnavailable, match='storage_data_invalid') as caught:
        store.get(mid) if table == 'missions' else store.events(mid)
    assert 'fixture-private-content' not in ''.join(traceback.format_exception(caught.value))
    assert 'fixture-private-content' not in incident_path.read_text()
    assert store.unavailable is True


def test_sqlite_lock_wait_is_bounded_and_incident_uses_independent_log(database):
    store, path, incident_path = database
    mid = store.create(REQUEST)
    state = store.get(mid)
    locker = sqlite3.connect(path)
    try:
        locker.execute('BEGIN IMMEDIATE')
        started = time.monotonic()
        with pytest.raises(StorageUnavailable, match='storage_sqlite_error'):
            store.save(state, 'heartbeat', {'status': 'pending'})
        assert time.monotonic() - started < 1.5
        assert records(incident_path)[0]['data']['code'] == 'storage_sqlite_error'
    finally:
        locker.rollback()
        locker.close()


def test_incidents_can_be_read_without_sqlite_and_drop_unrecognized_fields(database):
    store, path, incident_path = database
    mid = store.create(REQUEST)
    path.unlink()
    with pytest.raises(StorageUnavailable):
        store.get(mid)
    failure = records(incident_path)[0]
    tampered = {**failure, 'exception': 'fixture-private-content',
                'data': {**failure['data'], 'sql': 'fixture-private-content'}}
    with incident_path.open('a') as stream:
        for _ in range(130):
            stream.write(json.dumps(tampered) + '\n')
        stream.write('{"kind":"unrecognized","secret":"fixture-private-content"}\n')
        stream.write('not valid json\n')
    result = store.incidents(3)
    assert len(result) == 3
    assert all(event == failure for event in result)
    assert 'fixture-private-content' not in json.dumps(result)
    assert len(store.incidents(1000)) == 100
    assert store.unavailable is True


def test_incident_read_failure_is_sanitized_without_accessing_database(database):
    store, path, _ = database
    store.db.incident_log.path = path.parent
    with pytest.raises(StorageUnavailable, match='incident_log_unavailable'):
        store.incidents()
    assert store.unavailable is False
