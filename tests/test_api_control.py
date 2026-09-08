import asyncio
import time
from fastapi.testclient import TestClient
from app.main import create_app

TOKEN = 'operator-test-' + 'x' * 40
AUTH = {'Authorization': 'Bearer ' + TOKEN}
REQUEST = {'subject':'Veille agents IA', 'domains':['example.com'], 'action_budget':3, 'duration_minutes':1}

class WaitingProvider:
    def __init__(self):
        self.calls = 0
    async def decide(self, context):
        self.calls += 1
        await asyncio.sleep(60)
        return 'finish', {}, {}

def test_switch_auth_persistence_and_no_calls_while_disabled(tmp_path):
    provider = WaitingProvider()
    path = str(tmp_path / 'db')
    def app():
        return create_app(db_path=path, access_token=TOKEN, provider=provider)
    with TestClient(app()) as client:
        assert client.post('/api/control', json={'enabled':False}).status_code == 401
        assert client.post('/api/control', headers=AUTH, json={'enabled':'false'}).status_code == 422
        state = client.post('/api/control', headers=AUTH, json={'enabled':False}).json()
        assert state['api_enabled'] is False
        assert state['api_changed_at']
        assert client.post('/api/missions', headers=AUTH, json=REQUEST).status_code == 409
        assert client.get('/api/watches', headers=AUTH).status_code == 200
        assert provider.calls == 0
    with TestClient(app()) as client:
        assert client.get('/api/config', headers=AUTH).json()['api_enabled'] is False
        assert client.post('/api/missions', headers=AUTH, json=REQUEST).status_code == 409
        assert provider.calls == 0
        assert client.post('/api/control', headers=AUTH, json={'enabled':True}).json()['api_enabled'] is True
        response = client.post('/api/missions', headers=AUTH, json=REQUEST)
        assert response.status_code == 202
        mid = response.json()['id']
        for _ in range(100):
            if provider.calls: break
            time.sleep(.01)
        assert provider.calls == 1
        off = client.post('/api/control', headers=AUTH, json={'enabled':False}).json()
        assert mid in off['stopping_missions']
        for _ in range(100):
            state = client.get('/api/missions/' + mid, headers=AUTH).json()
            if state['status'] == 'stopped': break
            time.sleep(.01)
        assert state['status'] == 'stopped'
        events = client.get('/api/missions/' + mid + '/events', headers=AUTH).json()
        assert any(e['kind'] == 'stop_requested' and e['data']['reason'] == 'api_disabled' and e['at'] for e in events)
        assert provider.calls == 1
        assert client.post('/api/control', headers=AUTH, json={'enabled':True}).status_code == 200
        assert client.get('/api/missions/' + mid, headers=AUTH).json()['status'] == 'stopped'
