"""Palier 4 : arrêts et dépendances en panne, sans réseau ni crédit API.

Les scénarios observent les effets (appel annulé, fin sans nouvel appel,
chronologie du journal et réponse HTTP), pas les détails de la boucle.
"""
import asyncio
from datetime import datetime
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.engine import Engine
from app.agent.provider import AnthropicProvider
from app.agent.web import ToolFailure
from app.main import create_app
from app.schemas import MissionInput
from app.storage import Store

REQUEST = {
    'subject': 'Nouveautés des outils de recherche',
    'domains': ['example.com'],
    'action_budget': 8,
    'duration_minutes': 1,
}
TOKEN = 'resilience-test-only-' + 'x' * 32
AUTH = {'Authorization': 'Bearer ' + TOKEN}
SECRET = 'upstream-secret-must-not-appear'


def create_mission(store):
    return store.create(MissionInput(**REQUEST))


def events_of(state, kind):
    return [event for event in state['events'] if event['kind'] == kind]


def assert_chronological(events):
    assert [event['seq'] for event in events] == sorted(event['seq'] for event in events)
    dates = [datetime.fromisoformat(event['at']) for event in events]
    assert dates == sorted(dates)
    assert all(value.tzinfo is not None for value in dates)


def operation_id(event):
    return event['data'].get('operation_id', event['data'].get('id'))


def assert_operation_pair(state, operation, outcome):
    ends = [event for event in events_of(state, 'operation_finished')
            if event['data']['operation'] == operation and event['data']['outcome'] == outcome]
    assert ends, f'Aucune fin {outcome} pour {operation}'
    end = ends[-1]
    starts = [event for event in events_of(state, 'operation_started')
              if operation_id(event) == operation_id(end)]
    assert len(starts) == 1
    start = starts[0]
    assert operation_id(end)
    assert start['seq'] < end['seq']
    assert start['data']['dependency'] == end['data']['dependency']
    assert datetime.fromisoformat(start['at']) <= datetime.fromisoformat(end['at'])
    return start, end


class BlockingScenario:
    """Attend indéfiniment à l'étape choisie ; seule l'annulation le libère."""
    def __init__(self, stage):
        self.stage = stage
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.calls = []

    async def block(self):
        self.entered.set()
        try:
            await asyncio.Future()
        finally:
            self.cancelled.set()

    async def decide(self, context):
        self.calls.append('decide')
        if not context.get('scope_approved'):
            return 'accept_scope', {}, {}
        if self.stage == 'decide':
            await self.block()
        if self.stage == 'search_web':
            return 'search_web', {'query': 'Nouveautés documentaires', 'k': 1}, {}
        return 'read_page', {'url': 'https://example.com/news'}, {}

    async def search(self, *args):
        self.calls.append('search_web')
        await self.block()

    def reader_factory(self, reserve):
        owner = self

        class Reader:
            async def read(self, *args):
                owner.calls.append('read_page')
                reserve()
                await owner.block()

        return Reader()


@pytest.mark.parametrize('stage', ['decide', 'search_web', 'read_page'])
def test_operator_stop_cancels_each_inflight_dependency_once(tmp_path, stage):
    async def scenario():
        store = Store(str(tmp_path / 'stop.db'))
        provider = BlockingScenario(stage)
        engine = Engine(store, provider, provider.reader_factory)
        try:
            mid = create_mission(store)
            engine.launch(mid)
            await asyncio.wait_for(provider.entered.wait(), 2)
            running = store.get(mid)
            assert running['current_operation']['operation'] == stage
            calls_before = list(provider.calls)
            engine.stop(mid)
            engine.stop(mid)
            await asyncio.wait_for(asyncio.gather(engine.tasks[mid], return_exceptions=True), 2)
            engine.stop(mid)
            state = store.snapshot(mid)
            assert state['status'] == 'stopped'
            assert provider.cancelled.is_set()
            assert provider.calls == calls_before
            assert not engine.active()
            assert state['current_action'] is None
            assert state.get('current_operation') is None
            requests = events_of(state, 'stop_requested')
            assert len(requests) == 1
            assert requests[0]['data']['reason'] == 'operator'
            _, end = assert_operation_pair(state, stage, 'cancelled')
            assert requests[0]['seq'] < end['seq'] < events_of(state, 'finished')[0]['seq']
            assert not [event for event in state['events']
                        if event['seq'] > requests[0]['seq'] and event['kind'] in
                        {'operation_started', 'action_started', 'model_started', 'network_started'}]
            assert not events_of(state, 'dependency_failed'), 'Un arrêt volontaire ne simule pas une panne'
            assert_chronological(state['events'])
        finally:
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('stage', ['decide', 'search_web', 'read_page'])
def test_server_shutdown_is_a_controlled_stop_not_a_dependency_failure(tmp_path, stage):
    async def scenario():
        store = Store(str(tmp_path / 'shutdown.db'))
        provider = BlockingScenario(stage)
        engine = Engine(store, provider, provider.reader_factory)
        try:
            mid = create_mission(store)
            engine.launch(mid)
            await asyncio.wait_for(provider.entered.wait(), 2)
            before = list(provider.calls)
            await asyncio.wait_for(engine.close(), 2)
            await engine.close()
            state = store.snapshot(mid)
            assert state['status'] == 'stopped'
            assert state['error'] is None
            assert provider.calls == before
            assert provider.cancelled.is_set()
            stops = events_of(state, 'stop_requested')
            assert len(stops) == 1
            assert stops[0]['data']['reason'] == 'server_shutdown'
            assert len(events_of(state, 'finished')) == 1
            assert_operation_pair(state, stage, 'cancelled')
            assert not events_of(state, 'dependency_failed')
        finally:
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('shutdown', [False, True])
def test_stop_before_worker_starts_has_one_terminal_trace(tmp_path, shutdown):
    async def scenario():
        store = Store(str(tmp_path / 'early-stop.db'))
        provider = BlockingScenario('decide')
        engine = Engine(store, provider, provider.reader_factory)
        try:
            mid = create_mission(store)
            engine.launch(mid)
            if shutdown:
                await engine.close()
            else:
                engine.stop(mid)
                await asyncio.gather(engine.tasks[mid], return_exceptions=True)
            await asyncio.sleep(0)
            state = store.snapshot(mid)
            assert provider.calls == []
            assert state['status'] == 'stopped'
            assert len(events_of(state, 'finished')) == 1
            requests = events_of(state, 'stop_requested')
            assert len(requests) == 1
            assert requests[0]['data']['reason'] == ('server_shutdown' if shutdown else 'operator')
            assert not events_of(state, 'operation_started')
        finally:
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('stage', ['decide', 'search_web', 'read_page'])
def test_deadline_interrupts_an_await_without_new_action_or_false_dependency_failure(tmp_path, stage):
    async def scenario():
        store = Store(str(tmp_path / 'deadline.db'))
        provider = BlockingScenario(stage)
        engine = Engine(store, provider, provider.reader_factory)
        try:
            mid = create_mission(store)
            data = store.get(mid)
            # Horloge de mission avancée uniquement dans cette base de test.
            data['started_epoch'] = time.time() - 59.8
            store.save(data, 'test_deadline', {})
            engine.launch(mid)
            await asyncio.wait_for(provider.entered.wait(), 1)
            before = list(provider.calls)
            await asyncio.wait_for(engine.tasks[mid], 1)
            state = store.snapshot(mid)
            assert state['status'] == 'deadline_reached'
            assert provider.cancelled.is_set()
            assert provider.calls == before
            assert state.get('current_operation') is None
            assert state['current_action'] is None
            assert not events_of(state, 'dependency_failed'), 'La limite choisie ne doit pas devenir une fausse panne'
            _, end = assert_operation_pair(state, stage, 'cancelled')
            assert end['data']['code'] == 'deadline_reached'
            assert end['seq'] < events_of(state, 'finished')[0]['seq']
            assert_chronological(state['events'])
        finally:
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


class FailingModel:
    def __init__(self, stage, code):
        self.stage, self.code = stage, code
        self.calls = []

    async def decide(self, context):
        self.calls.append('decide')
        if not context.get('scope_approved'):
            return 'accept_scope', {}, {}
        if self.stage == 'decide':
            raise ToolFailure(self.code)
        return 'search_web', {'query': 'Nouveautés documentaires', 'k': 1}, {}

    async def search(self, *args):
        self.calls.append('search_web')
        raise ToolFailure(self.code)


@pytest.mark.parametrize('stage', ['decide', 'search_web'])
@pytest.mark.parametrize('code', [
    'anthropic_http_401', 'anthropic_http_403', 'anthropic_timeout',
    'anthropic_network_error', 'anthropic_invalid_response', 'timeout',
])
def test_provider_failure_stops_without_a_second_paid_attempt(tmp_path, stage, code):
    async def scenario():
        store = Store(str(tmp_path / 'failure.db'))
        provider = FailingModel(stage, code)
        engine = Engine(store, provider)
        try:
            mid = create_mission(store)
            await engine.run(mid)
            state = store.snapshot(mid)
            assert state['status'] == 'failed'
            assert state['error'] == code
            assert provider.calls == (['decide', 'decide'] if stage == 'decide'
                                      else ['decide', 'decide', 'search_web'])
            failures = events_of(state, 'dependency_failed')
            assert len(failures) == 1
            failure = failures[0]
            assert failure['data']['dependency'] == 'model_provider'
            assert failure['data']['operation'] == stage
            assert failure['data']['code'] == code
            assert failure['data']['reaction'] == 'stop'
            start, end = assert_operation_pair(state, stage, 'error')
            assert start['seq'] < failure['seq'] < events_of(state, 'finished')[0]['seq']
            assert end['seq'] < events_of(state, 'finished')[0]['seq']
            assert not [event for event in state['events'] if event['seq'] > failure['seq']
                        and event['kind'] in {'operation_started', 'action_started', 'model_started'}]
            assert_chronological(state['events'])
        finally:
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('code', ['unavailable', 'timeout'])
def test_page_failure_returns_to_model_and_retries_remain_bounded(tmp_path, code):
    async def scenario():
        calls = []
        contexts = []

        class Provider:
            async def decide(self, context):
                if not context.get('scope_approved'):
                    return 'accept_scope', {}, {}
                contexts.append(context)
                if len(contexts) <= 3:
                    return 'read_page', {'url': 'https://example.com/news'}, {}
                return 'finish', {}, {}

        class Reader:
            def __init__(self, reserve):
                self.reserve = reserve

            async def read(self, *args):
                self.reserve()
                calls.append('read')
                raise ToolFailure(code)

        store = Store(str(tmp_path / 'pages.db'))
        engine = Engine(store, Provider(), Reader)
        try:
            mid = create_mission(store)
            await engine.run(mid)
            state = store.snapshot(mid)
            assert state['status'] == 'completed'
            assert state['summary']['partial']
            assert calls == ['read', 'read']
            assert contexts[1]['recent_results'][-1]['result']['error'] == code
            assert contexts[-1]['recent_results'][-1]['result']['error'] == 'attempts_exhausted'
            failures = [event for event in events_of(state, 'dependency_failed')
                        if event['data']['dependency'] == 'web_page']
            assert len(failures) == 2
            assert all(event['data']['reaction'] == 'continue' for event in failures)
            assert all(event['data']['operation'] == 'read_page' and event['data']['code'] == code
                       for event in failures)
            assert_operation_pair(state, 'read_page', 'error')
            assert_chronological(state['events'])
        finally:
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


def install_mock_client(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr('app.agent.provider.httpx.AsyncClient',
                        lambda **kwargs: original(**kwargs, transport=transport))


@pytest.mark.parametrize('method', ['message', 'message_streaming'])
@pytest.mark.parametrize('status', [401, 403])
def test_anthropic_auth_failure_has_precise_code_and_never_leaks_body(monkeypatch, method, status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text=SECRET)

    install_mock_client(monkeypatch, handle)
    provider = AnthropicProvider('non-secret-fixture-key', 'fixture-model')
    with pytest.raises(ToolFailure) as caught:
        asyncio.run(getattr(provider, method)([], 'fixture', []))
    assert caught.value.code == f'anthropic_http_{status}'
    assert SECRET not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize('method', ['message', 'message_streaming'])
@pytest.mark.parametrize('exception,code', [
    (httpx.ConnectError, 'anthropic_network_error'),
    (httpx.ReadTimeout, 'anthropic_timeout'),
])
def test_anthropic_transport_failure_is_classified_without_retry(monkeypatch, method, exception, code):
    calls = []

    def handle(request):
        calls.append(request)
        raise exception(SECRET, request=request)

    install_mock_client(monkeypatch, handle)
    provider = AnthropicProvider('non-secret-fixture-key', 'fixture-model')
    with pytest.raises(ToolFailure) as caught:
        asyncio.run(getattr(provider, method)([], 'fixture', []))
    assert caught.value.code == code
    assert SECRET not in str(caught.value)
    assert len(calls) == 1


def test_invalid_provider_json_is_classified_without_exposing_body(monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, text=SECRET)

    install_mock_client(monkeypatch, handle)
    provider = AnthropicProvider('non-secret-fixture-key', 'fixture-model')
    with pytest.raises(ToolFailure) as caught:
        asyncio.run(provider.message([], 'fixture', []))
    assert caught.value.code == 'anthropic_invalid_response'
    assert SECRET not in str(caught.value)
    assert len(calls) == 1


def test_stream_eof_does_not_turn_a_partial_tool_call_into_success(monkeypatch):
    chunks = [
        {'type': 'message_start', 'message': {'usage': {}}},
        {'type': 'content_block_start', 'index': 0,
         'content_block': {'type': 'tool_use', 'name': 'accept_scope', 'input': {}}},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}},
    ]
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              text=''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks))

    install_mock_client(monkeypatch, handle)
    provider = AnthropicProvider('non-secret-fixture-key', 'fixture-model')
    with pytest.raises(ToolFailure) as caught:
        asyncio.run(provider.message_streaming([], 'fixture', []))
    assert caught.value.code == 'anthropic_stream_interrupted'
    assert len(calls) == 1


def test_incident_journal_requires_auth_even_when_empty(tmp_path):
    provider = FailingModel('decide', 'anthropic_http_403')
    app = create_app(db_path=str(tmp_path / 'incidents.db'), access_token=TOKEN, provider=provider)
    with TestClient(app) as client:
        assert client.get('/api/incidents').status_code == 401
        wrong = {'Authorization': 'Bearer ' + 'wrong-token-' + 'y' * 32}
        assert client.get('/api/incidents', headers=wrong).status_code == 401
        response = client.get('/api/incidents', headers=AUTH)
        assert response.status_code == 200
        assert response.json() == []
        assert provider.calls == []


def test_database_disappearance_stops_work_without_waiting_for_a_browser_request(tmp_path):
    entered, cancelled = threading.Event(), threading.Event()
    calls = []

    class Provider:
        async def decide(self, context):
            calls.append('decide')
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

    path = tmp_path / 'lost.db'
    app = create_app(db_path=str(path), access_token=TOKEN, provider=Provider())
    with TestClient(app) as client:
        app.state.engine.heartbeat_seconds = .01
        response = client.post('/api/missions', json=REQUEST, headers=AUTH)
        assert response.status_code == 202
        mid = response.json()['id']
        assert entered.wait(2)
        path.unlink()
        # Aucune requête HTTP pendant l'attente : c'est le heartbeat qui détecte la perte.
        deadline = time.monotonic() + 2
        while app.state.engine.active() and time.monotonic() < deadline:
            time.sleep(.005)
        assert not app.state.engine.active(), 'La perte du stockage doit interrompre le modèle en cours'
        assert cancelled.wait(.2)
        assert app.state.store.unavailable
        assert calls == ['decide']
        assert client.get('/health').status_code == 503
        for endpoint in [f'/api/missions/{mid}', f'/api/missions/{mid}/events', '/api/watches']:
            result = client.get(endpoint, headers=AUTH)
            assert result.status_code == 503, endpoint
            assert result.json() == {
                'detail': 'storage_file_missing', 'dependency': 'sqlite', 'reaction': 'stop',
            }
        result = client.post('/api/missions', headers=AUTH, json=REQUEST)
        assert result.status_code == 503
        assert calls == ['decide']
        assert client.get('/api/incidents').status_code == 401
        incidents = client.get('/api/incidents', headers=AUTH)
        assert incidents.status_code == 200
        entries = incidents.json()
        assert len(entries) == 1
        incident = entries[0]
        assert incident['kind'] == 'dependency_failed'
        assert incident['data']['dependency'] == 'sqlite'
        assert incident['data']['code'] == 'storage_file_missing'
        assert incident['data']['reaction'] == 'stop'
        assert datetime.fromisoformat(incident['at']).tzinfo is not None
        assert str(path) not in incidents.text
        assert client.get('/api/incidents', headers=AUTH).json() == entries
        assert calls == ['decide'], 'Lire le secours ne doit ni relancer la mission ni appeler le modèle'


class UncooperativeScenario(BlockingScenario):
    """Ignore l'annulation, mais reste libérable pour ne laisser aucune tâche au test."""
    def __init__(self, stage):
        super().__init__(stage)
        self.release = asyncio.Event()

    async def block(self):
        self.entered.set()
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()

    async def decide(self, context):
        self.calls.append('decide')
        if not context.get('scope_approved'):
            return 'accept_scope', {}, {}
        if self.stage == 'decide':
            await self.block()
        if self.stage in {'decide', 'search_web'}:
            return 'search_web', {'query': 'Résultat arrivé trop tard', 'k': 1}, {}
        return 'read_page', {'url': 'https://example.com/news'}, {}

    async def search(self, *args):
        self.calls.append('search_web')
        await self.block()
        return [{'url': 'https://example.com/late', 'title': 'Réponse tardive'}], {}

    def reader_factory(self, reserve):
        owner = self

        class Reader:
            async def read(self, *args):
                owner.calls.append('read_page')
                reserve()
                await owner.block()
                return {
                    'source_id': 'late-source', 'url': 'https://example.com/news',
                    'title': 'Réponse tardive', 'text': 'Ne doit pas être conservé.',
                    'status': 'ok', 'error': None, 'published_at': None,
                }

        return Reader()


@pytest.mark.parametrize('stage', ['decide', 'search_web', 'read_page'])
@pytest.mark.parametrize('stop_reason', ['operator', 'server_shutdown'])
def test_uncooperative_dependency_is_unknown_then_late_result_is_ignored(tmp_path, stage, stop_reason):
    async def scenario():
        store = Store(str(tmp_path / 'uncooperative.db'))
        provider = UncooperativeScenario(stage)
        engine = Engine(store, provider, provider.reader_factory)
        engine.heartbeat_seconds = .01
        engine.stop_grace_seconds = .02
        try:
            mid = create_mission(store)
            engine.launch(mid)
            await asyncio.wait_for(provider.entered.wait(), 2)
            before = list(provider.calls)
            if stop_reason == 'operator':
                engine.stop(mid)
            else:
                started = time.monotonic()
                await asyncio.wait_for(engine.close(), .5)
                assert time.monotonic() - started < .5
            await asyncio.wait_for(provider.cancelled.wait(), .5)
            deadline = time.monotonic() + .5
            while store.get(mid)['status'] != 'failed' and time.monotonic() < deadline:
                await asyncio.sleep(.005)
            state = store.snapshot(mid)
            assert state['status'] == 'failed'
            assert state['error'] == 'cancellation_unconfirmed'
            assert mid in engine.unconfirmed_stops
            assert not engine.tasks[mid].done(), 'Le test doit bien garder la dépendance non coopérative en attente'
            requests = events_of(state, 'stop_requested')
            assert len(requests) == 1 and requests[0]['data']['reason'] == stop_reason
            failures = events_of(state, 'dependency_failed')
            assert len(failures) == 1
            assert failures[0]['data']['code'] == 'cancellation_unconfirmed'
            assert failures[0]['data']['operation'] == stage
            assert failures[0]['data']['reaction'] == 'stop'
            _, end = assert_operation_pair(state, stage, 'unknown')
            assert requests[0]['seq'] < failures[0]['seq'] < end['seq']
            assert end['seq'] < events_of(state, 'finished')[0]['seq']
            assert not [event for event in events_of(state, 'operation_finished')
                        if event['data']['operation'] == stage and event['data']['outcome'] == 'cancelled']
            assert state['current_action'] is None and state.get('current_operation') is None
            assert provider.calls == before
            # Même un deuxième close ne doit pas attendre indéfiniment la dépendance.
            await asyncio.wait_for(engine.close(), .5)
            saved_events = store.events(mid)
            provider.release.set()
            await asyncio.wait_for(asyncio.gather(engine.tasks[mid], return_exceptions=True), .5)
            assert provider.calls == before
            assert store.events(mid) == saved_events, 'Un résultat tardif ne doit plus écrire dans le journal'
            assert store.snapshot(mid)['status'] == 'failed'
            assert store.snapshot(mid)['sources'] == []
            assert_chronological(state['events'])
        finally:
            provider.release.set()
            await asyncio.wait_for(asyncio.gather(*engine.tasks.values(), return_exceptions=True), 1)
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


def test_api_blocks_new_work_after_an_unconfirmed_stop_even_after_late_return(tmp_path):
    entered, ignored, release, returned = [threading.Event() for _ in range(4)]
    calls = []

    class Provider:
        async def decide(self, context):
            calls.append('decide')
            entered.set()
            try:
                while not release.is_set():
                    try:
                        await asyncio.sleep(.005)
                    except asyncio.CancelledError:
                        ignored.set()
                return 'accept_scope', {}, {}
            finally:
                returned.set()

    app = create_app(db_path=str(tmp_path / 'unconfirmed-api.db'), access_token=TOKEN, provider=Provider())
    with TestClient(app) as client:
        app.state.engine.heartbeat_seconds = .01
        app.state.engine.stop_grace_seconds = .02
        try:
            response = client.post('/api/missions', json=REQUEST, headers=AUTH)
            assert response.status_code == 202
            mid = response.json()['id']
            assert entered.wait(2)
            stop = client.post(f'/api/missions/{mid}/stop', headers=AUTH)
            assert stop.status_code == 200
            assert stop.json()['status'] in {'stopping', 'failed'}
            assert ignored.wait(.5)
            deadline = time.monotonic() + .5
            state = stop.json()
            while state['status'] != 'failed' and time.monotonic() < deadline:
                time.sleep(.005)
                state = client.get(f'/api/missions/{mid}', headers=AUTH).json()
            assert state['status'] == 'failed'
            assert state['error'] == 'cancellation_unconfirmed'
            assert client.post('/api/missions', json=REQUEST, headers=AUTH).status_code == 503
            assert calls == ['decide']
            saved_events = client.get(f'/api/missions/{mid}/events', headers=AUTH).json()
            release.set()
            assert returned.wait(.5)
            deadline = time.monotonic() + .5
            while app.state.engine.active() and time.monotonic() < deadline:
                time.sleep(.005)
            assert not app.state.engine.active()
            assert client.post('/api/missions', json=REQUEST, headers=AUTH).status_code == 503
            assert calls == ['decide']
            assert client.get(f'/api/missions/{mid}/events', headers=AUTH).json() == saved_events
        finally:
            release.set()
            assert returned.wait(1)
