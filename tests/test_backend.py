import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.schemas import MissionInput
from app.storage import Store
from app.agent.engine import Engine
from app.agent.web import ToolFailure, check_url

TOKEN = 'test-operator-token-only-' + 'x'*32
AUTH = {'Authorization':'Bearer '+TOKEN}
REQUEST = {'subject':'Agents IA', 'domains':['example.com'], 'action_budget':10, 'duration_minutes':1}
PAGE = {'source_id':'source1','url':'https://example.com/news','title':'Actualité',
        'text':'Une nouvelle bibliothèque pour les agents est disponible.',
        'retrieved_at':'2026-09-07T12:00:00+00:00','published_at':None,'status':'ok','error':None}


class Scripted:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.calls = 0

    async def decide(self, context):
        if not context.get('scope_approved'):
            return 'accept_scope', {}, {}
        self.calls += 1
        name, args = next(self.actions, ('finish', {}))
        return name, args, {}

    async def search(self, query, k, domains):
        return [{'url':PAGE['url'],'title':PAGE['title']}], {}


class Reader:
    def __init__(self, reserve):
        self.reserve = reserve

    async def read(self, url, domains):
        self.reserve()
        return PAGE.copy()


def finding():
    return {'finding':{'title':'Bibliothèque', 'summary':'Nouvelle bibliothèque.',
            'developer_impact':'À examiner pour créer des agents.',
            'evidence':[{'source_id':'source1','quote':'Une nouvelle bibliothèque'}]},
            'idempotency_key':'finding1'}


def test_end_to_end_persistence(tmp_path):
    path = str(tmp_path/'db.sqlite')
    provider = Scripted([('search_web',{'query':'agent','k':2}), ('read_page',{'url':PAGE['url']}),
                         ('save_finding',finding()), ('save_finding',finding())])
    app = create_app(db_path=path, access_token=TOKEN, provider=provider)
    with TestClient(app) as client:
        app.state.engine.reader_factory = Reader
        response = client.post('/api/missions', json=REQUEST, headers=AUTH)
        assert response.status_code == 202
        mid = response.json()['id']
        for _ in range(100):
            state = client.get('/api/missions/'+mid, headers=AUTH).json()
            if state['status'] == 'completed': break
            time.sleep(.005)
        assert state['status'] == 'completed', state
        assert len(state['findings']) == 1
        assert state['actions_used'] == 4
        assert state['findings'][0]['date_status'] == 'unknown'
        assert 'pages' not in state
    with TestClient(create_app(db_path=path, access_token=TOKEN, provider=provider)) as client:
        assert client.get('/api/missions/'+mid, headers=AUTH).json()['findings'] == state['findings']


def test_auth_validation_and_config(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path/'db'), access_token=TOKEN, provider=Scripted([]))) as client:
        assert client.get('/health').status_code == 200
        assert client.post('/api/missions', json=REQUEST).status_code == 401
        assert client.post('/api/missions', headers=AUTH, json={**REQUEST,'domains':['127.0.0.1']}).status_code == 422
        assert client.post('/api/missions', headers=AUTH, json={**REQUEST,'action_budget':101}).status_code == 422
        assert client.post('/api/missions', headers=AUTH, json={**REQUEST,'domains':['https://example.com']}).status_code == 422


@pytest.mark.parametrize('url', ['http://example.com','https://example.com:444/',
    'https://example.com@127.0.0.1/', 'https://sub.example.com/', 'https://localhost/',
    'https://example.com.evil.org/', 'file:///etc/passwd'])
def test_url_policy(url):
    with pytest.raises(ToolFailure): check_url(url, ['example.com'])


def test_budget_counts_invalid_tools(tmp_path):
    async def scenario():
        store = Store(str(tmp_path/'db'))
        mid = store.create(MissionInput(**{**REQUEST,'action_budget':1}))
        engine = Engine(store, Scripted([('unknown',{})]), Reader)
        await engine.run(mid)
        state = store.snapshot(mid)
        assert state['status'] == 'budget_exhausted'
        assert state['actions_used'] == 1
        assert any(e['kind']=='tool_error' for e in state['events'])
    asyncio.run(scenario())


def test_stop_cancels_inflight_and_no_next_action(tmp_path):
    async def scenario():
        started = asyncio.Event()
        class Slow(Scripted):
            async def decide(self, context):
                if not context.get('scope_approved'):
                    return 'accept_scope', {}, {}
                self.calls += 1
                started.set()
                await asyncio.sleep(60)
        store = Store(str(tmp_path/'db'))
        mid = store.create(MissionInput(**REQUEST))
        provider = Slow([])
        engine = Engine(store, provider)
        engine.launch(mid)
        await started.wait()
        engine.stop(mid)
        await engine.tasks[mid]
        engine.stop(mid)
        assert store.snapshot(mid)['status'] == 'stopped'
        assert provider.calls == 1
        assert store.snapshot(mid)['actions_used'] == 0
    asyncio.run(scenario())


def test_deadline_and_recovery(tmp_path):
    async def scenario():
        store = Store(str(tmp_path/'db'))
        mid = store.create(MissionInput(**REQUEST))
        d = store.get(mid); d['started_epoch'] -= 120; store.save(d,'test_clock',{})
        await Engine(store, Scripted([])).run(mid)
        assert store.snapshot(mid)['status'] == 'deadline_reached'
        second = store.create(MissionInput(**REQUEST))
        store.recover()
        assert store.snapshot(second)['status'] == 'failed'
    asyncio.run(scenario())


def test_fabricated_evidence_rejected(tmp_path):
    async def scenario():
        store = Store(str(tmp_path/'db'))
        mid = store.create(MissionInput(**REQUEST))
        await Engine(store, Scripted([('save_finding',finding())]), Reader).run(mid)
        assert store.snapshot(mid)['findings'] == []
        assert any(e['data'].get('code') == 'invalid_evidence' for e in store.events(mid))
    asyncio.run(scenario())


def test_stop_before_worker_started(tmp_path):
    async def scenario():
        store = Store(str(tmp_path/'db'))
        mid = store.create(MissionInput(**REQUEST))
        engine = Engine(store, Scripted([]))
        engine.launch(mid)
        engine.stop(mid)
        await asyncio.gather(engine.tasks[mid], return_exceptions=True)
        await asyncio.sleep(0)
        assert store.snapshot(mid)['status'] == 'stopped'
    asyncio.run(scenario())


def test_attempts_cannot_be_reset(tmp_path):
    async def scenario():
        class Broken(Reader):
            calls = 0
            async def read(self, url, domains):
                Broken.calls += 1
                raise ToolFailure('unavailable')
        store = Store(str(tmp_path/'db'))
        mid = store.create(MissionInput(**REQUEST))
        await Engine(store, Scripted([('read_page', {'url':PAGE['url']})]*3), Broken).run(mid)
        assert Broken.calls == 2
        assert store.snapshot(mid)['actions_used'] == 3
    asyncio.run(scenario())


def test_dns_rejects_mixed_public_private(monkeypatch):
    from app.agent.web import PublicResolver
    import socket
    async def scenario():
        async def addresses(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8',443)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1',443))]
        monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', addresses)
        with pytest.raises(ToolFailure):
            await PublicResolver().resolve('example.com',443)
    asyncio.run(scenario())


def test_provider_failure_never_exposes_exception(tmp_path):
    class Bad(Scripted):
        async def decide(self, context):
            if not context.get('scope_approved'):
                return 'accept_scope', {}, {}
            raise RuntimeError('secret-example-value-must-not-leak')
    async def scenario():
        store = Store(str(tmp_path/'db'))
        mid = store.create(MissionInput(**REQUEST))
        await Engine(store, Bad([])).run(mid)
        state = store.snapshot(mid)
        assert state['status'] == 'failed'
        assert 'secret-example-value' not in json.dumps(state)
    asyncio.run(scenario())


def test_single_active_mission(tmp_path):
    class Slow(Scripted):
        async def decide(self, context):
            if not context.get('scope_approved'):
                return 'accept_scope', {}, {}
            await asyncio.sleep(60)
    app = create_app(db_path=str(tmp_path/'db'), access_token=TOKEN, provider=Slow([]))
    with TestClient(app) as client:
        assert client.post('/api/missions', json=REQUEST, headers=AUTH).status_code == 202
        assert client.post('/api/missions', json=REQUEST, headers=AUTH).status_code == 409


def test_search_keeps_hits_when_provider_reaches_search_cap():
    from app.agent.provider import AnthropicProvider
    class Provider(AnthropicProvider):
        async def message(self, *args):
            return {'content':[
                {'type':'web_search_tool_result','content':[{'type':'web_search_result','url':PAGE['url'],'title':'News'}]},
                {'type':'web_search_tool_result','content':{'error_code':'max_uses_exceeded'}}]}
    async def scenario():
        hits, usage = await Provider('test','test').search('news',3,['example.com'])
        assert hits[0]['url'] == PAGE['url']
    asyncio.run(scenario())
