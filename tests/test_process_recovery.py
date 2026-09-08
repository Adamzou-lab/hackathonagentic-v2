"""Une coupure réelle d'un processus de test, sans API ni base applicative."""
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from app.agent.engine import Engine
from app.schemas import MissionInput
from app.storage import Store
from scripts import palier4_fault


QUOTE = 'Ce constat de test a été vérifié avant la coupure.'
PAGE = {
    'source_id': 'fixture-page', 'url': 'https://example.com/fixture',
    'title': 'Publication simulée', 'text': QUOTE,
    'retrieved_at': '2026-09-08T12:00:00+00:00', 'published_at': None,
    'status': 'ok', 'error': None,
}


def append_trace(path, record):
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


async def fixture_child(database, readiness, calls_path, incidents):
    """Le test exécute ce moteur en subprocess ; aucun fournisseur réel."""
    import socket

    def external_network_forbidden(*args, **kwargs):
        raise AssertionError('Le scénario de récupération interdit tout accès réseau.')

    socket.create_connection = external_network_forbidden
    socket.socket.connect = external_network_forbidden
    store = Store(database, incident_path=incidents)
    mid = store.create(MissionInput(
        subject='Veille fixture pour récupération après coupure',
        domains=['example.com'], action_budget=10, duration_minutes=1,
    ))

    class Provider:
        async def decide(self, context):
            append_trace(calls_path, {'call': 'decide', 'scope_approved': context.get('scope_approved', False)})
            if not context.get('scope_approved'):
                return 'accept_scope', {}, {}
            if context['saved_findings']:
                return 'search_web', {'query': 'Autre publication simulée', 'k': 1}, {}
            if context['recent_results']:
                return 'save_finding', {
                    'finding': {
                        'title': 'Constat conservé', 'summary': 'Résultat acquis avant interruption.',
                        'developer_impact': 'Permet de vérifier la conservation des preuves.',
                        'evidence': [{'source_id': PAGE['source_id'], 'quote': QUOTE}],
                    },
                    'idempotency_key': 'fixture-before-kill',
                }, {}
            return 'read_page', {'url': PAGE['url']}, {}

        async def search(self, *args):
            append_trace(calls_path, {'call': 'search_blocked'})
            state = store.get(mid)
            assert state['findings'] and state['current_action'] == 'search_web'
            assert state['current_operation']['operation'] == 'search_web'
            ready = {
                'mid': mid, 'operation_id': state['current_operation']['id'],
                'last_seen_at': state['last_seen_at'], 'child_pid': os.getpid(),
            }
            temporary = Path(readiness).with_suffix('.tmp')
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump(ready, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, readiness)
            # SIGKILL coupe réellement le processus pendant l'attente du moteur.
            await asyncio.Future()

    class Reader:
        def __init__(self, reserve):
            self.reserve = reserve

        async def read(self, *args):
            self.reserve()
            append_trace(calls_path, {'call': 'read_fixture'})
            return dict(PAGE)

    engine = Engine(store, Provider(), Reader)
    engine.heartbeat_seconds = .02
    try:
        engine.launch(mid)
        await engine.tasks[mid]
    finally:
        # Ce nettoyage sert uniquement si le test s'arrête sans SIGKILL.
        await engine.close()
        store.db.close()


@pytest.mark.skipif(os.name != 'posix', reason='Le témoin de coupure utilise SIGKILL sur macOS/Linux.')
def test_sigkill_recovery_keeps_proofs_and_marks_only_inflight_work_unknown(tmp_path, monkeypatch):
    database = tmp_path / 'isolated.db'
    readiness = tmp_path / 'child-ready.json'
    calls_path = tmp_path / 'fixture-calls.jsonl'
    incidents = tmp_path / 'storage-incidents.jsonl'
    witness = tmp_path / 'external-fault.jsonl'
    for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'LOCKIN_ACCESS_TOKEN', 'LOCKIN_DB_PATH'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PYTHONPATH', str(Path(__file__).resolve().parents[1]))
    command = [sys.executable, str(Path(__file__).resolve()), '--fixture-child',
               str(database), str(readiness), str(calls_path), str(incidents)]

    # Le superviseur reçoit la commande opérateur seulement après readiness.
    read_fd, write_fd = os.pipe()
    command_input = os.fdopen(read_fd, 'r', encoding='utf-8')
    monkeypatch.setattr(palier4_fault.sys, 'stdin', command_input)
    audit = palier4_fault.Audit(witness)
    children, outcomes, supervisor_errors = [], [], []
    original_popen = subprocess.Popen

    def own_child(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(palier4_fault.subprocess, 'Popen', own_child)

    def run_supervisor():
        try:
            outcomes.append(palier4_fault.supervise(command, audit))
        except BaseException as error:
            supervisor_errors.append(error)

    supervisor = threading.Thread(target=run_supervisor, daemon=True)
    supervisor.start()
    ready = None
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and supervisor.is_alive():
            if readiness.exists():
                ready = json.loads(readiness.read_text())
                break
            time.sleep(.01)
        assert ready is not None, 'Le moteur enfant doit atteindre une vraie opération en cours avant la coupure.'
        assert len(children) == 1 and children[0].pid == ready['child_pid']
        assert children[0].poll() is None
        os.write(write_fd, b'couper\n')
        supervisor.join(timeout=7)
        assert not supervisor.is_alive(), 'Le superviseur doit confirmer et récolter la sortie de son enfant.'
        assert not supervisor_errors
        assert outcomes == [0]
        assert children[0].returncode == -signal.SIGKILL
    finally:
        if supervisor.is_alive():
            try:
                os.write(write_fd, b'quitter\n')
            except OSError:
                pass
            supervisor.join(timeout=7)
        # Filet de nettoyage limité à l'objet Popen créé par CE test.
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=2)
        supervisor.join(timeout=1)
        os.close(write_fd)
        command_input.close()
        audit.close()

    external = [json.loads(line) for line in witness.read_text().splitlines()]
    applied = [event for event in external if event['kind'] == 'fault_applied']
    assert len(applied) == 1
    applied = applied[0]
    assert applied['data']['child_pid'] == ready['child_pid']
    assert applied['data']['interrupted_at'] is None
    assert applied['data']['returncode'] == -signal.SIGKILL
    assert applied['data']['requested_at'] <= applied['data']['applied_at'] <= applied['at']
    assert not [event for event in external if event['kind'] in {'fault_not_applied', 'fault_failed'}]
    calls_before = calls_path.read_bytes()
    assert json.loads(calls_before.splitlines()[-1]) == {'call': 'search_blocked'}

    recovered = Store(database, incident_path=incidents)
    try:
        before = recovered.get(ready['mid'])
        events_before = recovered.events(ready['mid'])
        assert before['status'] == 'running'
        assert len(before['findings']) == 1
        assert before['current_operation']['id'] == ready['operation_id']
        assert before['last_seen_at'] == events_before[-1]['at']
        assert datetime.fromisoformat(before['last_seen_at']) < datetime.fromisoformat(applied['data']['applied_at'])
        recovered.recover()
        state = recovered.snapshot(ready['mid'])
        assert state['status'] == 'failed' and state['error'] == 'process_interrupted'
        assert state['findings'] == before['findings']
        assert state['sources'] == before['sources']
        assert recovered.get(ready['mid'])['pages'] == before['pages']
        assert state['events'][:len(events_before)] == events_before
        assert state['current_action'] is None and state['current_operation'] is None
        recovery = next(event for event in state['events'] if event['kind'] == 'recovery_detected')
        assert recovery['data'] == {
            'last_seen_at': before['last_seen_at'], 'interrupted_at': None, 'reaction': 'stop',
        }
        assert datetime.fromisoformat(recovery['at']) > datetime.fromisoformat(applied['at'])
        operation_end = [event for event in state['events'] if event['kind'] == 'operation_finished'
                         and event['data']['operation_id'] == ready['operation_id']]
        assert len(operation_end) == 1
        assert operation_end[0]['data']['outcome'] == 'unknown'
        assert operation_end[0]['data']['code'] == 'interrupted'
        action_end = [event for event in state['events'] if event['kind'] == 'action_finished'
                      and event['data']['tool'] == 'search_web']
        assert len(action_end) == 1
        assert action_end[0]['data']['result'] == {'status': 'unknown', 'error': 'interrupted'}
        after_detection = state['events'][len(events_before):]
        assert not [event for event in after_detection
                    if event['kind'] in {'operation_started', 'action_started', 'model_started', 'network_started'}]
        recovered.recover()
        assert recovered.snapshot(ready['mid']) == state
        assert calls_path.read_bytes() == calls_before, 'La récupération ne doit relancer aucun appel fournisseur.'
    finally:
        recovered.db.close()


if __name__ == '__main__':
    if len(sys.argv) != 6 or sys.argv[1] != '--fixture-child':
        raise SystemExit('Ce fichier exécute uniquement son enfant de test explicite.')
    asyncio.run(fixture_child(*sys.argv[2:]))
