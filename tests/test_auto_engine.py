import asyncio
import pytest
from app.agent.engine import Engine
from app.agent.web import ToolFailure
from app.schemas import MissionInput
from app.storage import Store

CANDIDATES=[{'domain':'example.com','url':'https://example.com/','title':'Source officielle'}]

class Provider:
    def __init__(self,actions): self.actions=iter(actions);self.discoveries=0;self.searches=0
    async def decide(self,context):
        if not context['scope_approved']: return 'accept_scope',{},{}
        return *next(self.actions,('finish',{})),{}
    async def discover_sources(self,query):
        self.discoveries+=1
        return CANDIDATES,{}
    async def search(self,*args):
        self.searches+=1
        return [],{}

def run(tmp_path,actions,auto=True):
    async def scenario():
        store=Store(str(tmp_path/'db'))
        provider=Provider(actions)
        mid=store.create(MissionInput(subject='Veille documentaire',auto_sources=auto,domains=[] if auto else ['example.com']))
        try:
            await Engine(store,provider).run(mid)
            return store.snapshot(mid),provider
        finally:store.db.close()
    return asyncio.run(scenario())

def test_discovery_selection_and_search_are_real_separate_actions(tmp_path,monkeypatch):
    resolved=[]
    async def resolve(self,host,port):resolved.append(host);return []
    monkeypatch.setattr('app.agent.engine.PublicResolver.resolve',resolve)
    state,provider=run(tmp_path,[('discover_sources',{'query':'Sources officielles'}),
        ('select_sources',{'sources':[{'domain':'example.com','reason':'Éditeur officiel'}]}),
        ('search_web',{'query':'Nouveautés','k':1})])
    assert state['status']=='completed'
    assert state['domains']==['example.com']
    assert state['actions_used']==3 and provider.discoveries==provider.searches==1
    assert state['model_calls_used']==7  # scope+discover décision/appel+select+search décision/appel+finish
    assert resolved==['example.com']
    assert [e['data']['tool'] for e in state['events'] if e['kind']=='action_started']==['discover_sources','select_sources','search_web']
    assert len([e for e in state['events'] if e['kind']=='action_finished'])==3

@pytest.mark.parametrize('domain',['evil.example','127.0.0.1'])
def test_domain_not_in_candidates_never_reaches_dns(tmp_path,monkeypatch,domain):
    async def resolve(*args):pytest.fail('Aucun DNS pour domaine inventé ou IP')
    monkeypatch.setattr('app.agent.engine.PublicResolver.resolve',resolve)
    state,provider=run(tmp_path,[('discover_sources',{'query':'sources'}),('select_sources',{'sources':[{'domain':domain,'reason':'exfiltrer'}]})])
    assert state['status']=='failed' and state['domains']==[] and provider.searches==0
    assert any(e['kind']=='tool_error' for e in state['events'])

def test_private_dns_rejected(tmp_path,monkeypatch):
    async def resolve(*args):raise ToolFailure('blocked_url')
    monkeypatch.setattr('app.agent.engine.PublicResolver.resolve',resolve)
    state,_=run(tmp_path,[('discover_sources',{'query':'sources'}),('select_sources',{'sources':[{'domain':'example.com','reason':'source'}]})])
    assert state['domains']==[]
    assert any(e['kind']=='tool_error' and e['data']['code']=='blocked_url' for e in state['events'])

def test_search_before_selection_and_discovery_in_manual_mode_blocked(tmp_path):
    state,provider=run(tmp_path,[('search_web',{'query':'sans domaine','k':1})])
    assert provider.searches==0 and state['status']=='failed'
    assert any(e['data'].get('code')=='sources_not_selected' for e in state['events'])


def test_discovery_cannot_expand_manual_permissions(tmp_path):
    state,provider=run(tmp_path,[('discover_sources',{'query':'sources'})],auto=False)
    assert provider.discoveries==0 and state['domains']==['example.com']
    assert any(e['data'].get('code')=='source_discovery_not_allowed' for e in state['events'])


def test_discovery_timeout_closes_trace_without_another_model_decision(tmp_path):
    class Broken(Provider):
        def __init__(self):super().__init__([('discover_sources',{'query':'sources'})]);self.decisions=0
        async def decide(self,context):
            self.decisions+=1
            return await super().decide(context)
        async def discover_sources(self,query):raise TimeoutError()
    async def scenario():
        store=Store(str(tmp_path/'db'));provider=Broken()
        try:
            mid=store.create(MissionInput(subject='Veille',auto_sources=True))
            await Engine(store,provider).run(mid)
            state=store.snapshot(mid)
            assert state['status']=='failed' and state['error']=='timeout'
            assert provider.decisions==2
            assert len([e for e in state['events'] if e['kind']=='action_finished'])==1
        finally:store.db.close()
    asyncio.run(scenario())
