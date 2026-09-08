"""Contrôle du protocole de périmètre, sans appel au vrai modèle."""
import asyncio
import pytest
from app.agent.engine import Engine
from app.agent.provider import AnthropicProvider, SCOPE_TOOLS
from app.schemas import MissionInput
from app.storage import Store, TERMINAL

@pytest.mark.parametrize('decision', [
    ('refuse', {'code':'out_of_scope'}),
    ('refuse', {'code':[]}),
    ('search_web', {'query':'recette sandwich', 'k':1}),
    ('finish', {}),
    ('accept_scope', {'unexpected':True}),
])
def test_no_tool_before_scope_acceptance(tmp_path, decision):
    class Unapproved:
        async def decide(self, context):
            assert context['scope_approved'] is False
            return *decision, {}
        async def search(self, *args):
            pytest.fail('Aucune recherche avant validation du périmètre')
    async def run():
        store=Store(str(tmp_path/'db'))
        try:
            mid=store.create(MissionInput(subject='Prépare-moi un sandwich',domains=['example.com']))
            await Engine(store,Unapproved()).run(mid)
            state=store.snapshot(mid)
            assert state['status']=='refused' and state['status'] in TERMINAL
            assert state['actions_used']==0 and state['model_calls_used']==1
            assert state['refusal_reason']==state['summary']['text']
            assert any(e['kind']=='mission_refused' for e in state['events'])
            assert not any(e['kind']=='action_started' for e in state['events'])
        finally: store.db.close()
    asyncio.run(run())

@pytest.mark.parametrize('content', [[], [{'type':'text','text':'Non.'}],
    [{'type':'tool_use','name':'accept_scope','input':{},'truncated':True}],
    [{'type':'tool_use','name':'accept_scope','input':{}}]*2])
def test_ambiguous_model_output_refused(content):
    class Fake(AnthropicProvider):
        async def message(self, messages, system, tools):
            assert tools == SCOPE_TOOLS
            assert {t['name'] for t in tools} == {'accept_scope','refuse'}
            return {'content':content}
    action, args, _ = asyncio.run(Fake('fake','fake').decide({'scope_approved':False}))
    assert (action,args)==('refuse',{'code':'clarification_required'})


def test_refusal_reaches_authenticated_stream(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    class Refusing:
        async def decide(self, context):
            return 'refuse', {'code':'out_of_scope'}, {}
    headers={'Authorization':'Bearer '+'t'*40}
    with TestClient(create_app(db_path=str(tmp_path/'db'), access_token='t'*40, provider=Refusing())) as client:
        mid=client.post('/api/missions',headers=headers,json={
            'subject':'Prépare-moi un sandwich','domains':['example.com']}).json()['id']
        response=client.get(f'/api/missions/{mid}/stream',headers=headers)
        assert response.status_code==200
        assert 'mission_refused' in response.text
        assert 'event: end' in response.text
        assert '"status": "refused"' in response.text
        state=client.get(f'/api/missions/{mid}',headers=headers).json()
        assert state['status']=='refused' and state['actions_used']==0


def test_acceptance_is_counted_and_allows_normal_tools(tmp_path):
    class Accepted:
        def __init__(self): self.searches=0
        async def decide(self, context):
            if not context['scope_approved']: return 'accept_scope', {}, {}
            if not context['recent_results']: return 'search_web', {'query':'Actualité documentaire','k':1}, {}
            return 'finish', {}, {}
        async def search(self,*args):
            self.searches+=1
            return [], {}
    async def run():
        store=Store(str(tmp_path/'db'))
        try:
            mid=store.create(MissionInput(subject='Actualité des sandwichs',domains=['example.com']))
            provider=Accepted()
            await Engine(store,provider).run(mid)
            state=store.snapshot(mid)
            assert state['status']=='completed' and provider.searches==1
            assert state['model_calls_used']==4  # périmètre, décision, recherche, fin
            assert state['actions_used']==1
        finally: store.db.close()
    asyncio.run(run())
