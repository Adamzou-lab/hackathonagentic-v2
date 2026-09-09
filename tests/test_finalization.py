import asyncio
import time
import pytest
from app.agent.engine import Engine
from app.agent.engine import Halt
from app.agent.provider import AnthropicProvider
from app.schemas import MissionInput
from app.storage import Store

PAGE = {'source_id':'s1','url':'https://example.com/release','title':'Version',
        'text':'Une version documentée apporte un nouvel outil.', 'status':'ok',
        'retrieved_at':'2026-09-09T10:00:00+00:00','published_at':None}


@pytest.mark.parametrize('trigger', ['actions','tokens','time'])
def test_finalization_saves_before_stopping_without_extra_search(tmp_path, trigger):
    class Provider:
        calls = 0
        async def decide(self, ctx):
            self.calls += 1
            if not ctx['scope_approved']:
                return 'accept_scope', {}, {}
            assert ctx['finalization']
            return 'save_finding', {'idempotency_key':'one', 'finding':{
                'title':'Version', 'summary':PAGE['text'], 'developer_impact':'Lire la documentation.',
                'evidence':[{'source_id':'s1','passage_id':ctx['evidence_catalog'][0]['passages'][0]['passage_id']}]}}, {}
    async def scenario():
        store = Store(tmp_path/'db')
        try:
            mid = store.create(MissionInput(subject='Veille',domains=['example.com'],action_budget=10))
            d=store.get(mid); d['pages']={'s1':PAGE}
            if trigger=='actions': d['actions_used']=8
            if trigger=='time': d['started_epoch']=time.time()-590
            if trigger=='tokens': d['model_calls_used']=1
            store.save(d,'model_finished' if trigger=='tokens' else 'fixture',
                       {'usage':{'input_tokens':int(d['token_budget']*.72),'output_tokens':0}} if trigger=='tokens' else {})
            provider=Provider()
            await Engine(store,provider).run(mid)
            state=store.snapshot(mid)
            assert state['status']=='budget_exhausted'
            assert state['finalization_reason']==trigger
            assert len(state['findings'])==1 and PAGE['text'] in state['summary']['text']
            assert state['summary']['partial'] and provider.calls==2
            assert state['actions_used'] <= 10
        finally: store.db.close()
    asyncio.run(scenario())


def test_finalization_rejects_network_proposal_on_server(tmp_path):
    class Provider:
        async def decide(self,ctx):
            return ('accept_scope',{}, {}) if not ctx['scope_approved'] else ('read_page',{'url':PAGE['url']},{})
    class Reader:
        def __init__(self,*args): pass
        async def read(self,*args): raise AssertionError('Network must not be invoked')
    async def scenario():
        store=Store(tmp_path/'db')
        try:
            mid=store.create(MissionInput(subject='Veille',domains=['example.com'],action_budget=4))
            d=store.get(mid);d.update(actions_used=3,pages={'s1':PAGE});store.save(d,'fixture',{})
            await Engine(store,Provider(),Reader).run(mid)
            state=store.snapshot(mid)
            assert state['actions_used']==3 and not state['findings']
            assert any(e['kind']=='finalization_tool_blocked' for e in state['events'])
        finally:store.db.close()
    asyncio.run(scenario())


def test_model_only_sees_finalization_tools():
    class Provider(AnthropicProvider):
        async def message(self,messages,system,tools):
            assert {t['name'] for t in tools}=={'save_finding','finish','refuse'}
            return {'content':[{'type':'tool_use','name':'finish','input':{}}]}
    assert asyncio.run(Provider('fixture','fixture').decide({'scope_approved':True,
        'finalization':True,'mission':{'domains':['example.com']}}))[0]=='finish'


def test_second_paid_search_is_blocked(tmp_path):
    class Provider:
        calls=0
        async def search(self,*args):
            self.calls+=1
            return [], {'input_tokens':10,'output_tokens':1}
    async def scenario():
        store=Store(tmp_path/'db')
        try:
            mid=store.create(MissionInput(subject='Veille',domains=['example.com'],action_budget=10))
            provider=Provider(); engine=Engine(store,provider)
            await engine.execute(mid,'search_web',{'query':'actualités','k':1},None)
            with pytest.raises(Halt):
                await engine.execute(mid,'search_web',{'query':'autres actualités','k':1},None)
            assert provider.calls==1 and store.get(mid)['web_search_calls_used']==1
        finally:store.db.close()
    asyncio.run(scenario())


def test_automatic_sources_keep_room_after_discovery(tmp_path):
    store=Store(tmp_path/'db')
    try:
        mid=store.create(MissionInput(subject='Veille',auto_sources=True,action_budget=10))
        d=store.get(mid)
        assert d['token_budget']==48000 and d['finalization_reserve']==2
        assert d['web_search_limit']==1
    finally:store.db.close()


def test_model_schema_exposes_only_passage_reference():
    from app.agent.provider import TOOLS
    schema = next(t for t in TOOLS if t['name']=='save_finding')['input_schema']['$defs']['Evidence']
    assert 'quote' not in schema['properties']
    assert schema['required'] == ['source_id','passage_id']
    assert schema['properties']['passage_id']['type'] == 'string'
