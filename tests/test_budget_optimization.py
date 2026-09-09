import asyncio
import json
from app.agent.budget import finalization_token_reserve
from app.agent.provider import AnthropicProvider, SYSTEM, TOOLS
from app.agent.engine import Engine
from app.schemas import MissionInput
from app.storage import Store


def test_reserve_uses_decisions_not_large_native_search_results():
    def event(n, action=None):
        return {'kind':'model_finished','data':{'proposed_action':action,
            'usage':{'input_tokens':n,'output_tokens':100}}}
    events = [event(14000), event(2000,'read_page'), event(2200,'save_finding')]
    assert finalization_token_reserve(events,40000) == 4096
    assert finalization_token_reserve([event(14000)],40000) == 12000
    assert finalization_token_reserve([event(9000,'save_finding')],40000) > 11000


def test_known_unread_links_avoid_second_paid_search_and_keep_evidence_tools():
    class Provider(AnthropicProvider):
        async def message(self,messages,system,tools):
            names = {t['name'] for t in tools}
            assert 'search_web' not in names
            assert 'read_page' in names and 'save_finding' in names
            assert json.loads(messages[0]['content'])['evidence_catalog'][0]['passages'][0]['quote'] == 'Preuve réellement lue'
            return {'content':[{'type':'tool_use','name':'read_page','input':{'url':'https://example.com/b'}}]}
    ctx = {'scope_approved':True,'mission':{'domains':['example.com']},
           'available_sources':[{'url':'https://example.com/b'}],
           'evidence_catalog':[{'source_id':'a','passages':[{'quote':'Preuve réellement lue'}]}]}
    assert asyncio.run(Provider('fake','fake').decide(ctx))[0] == 'read_page'


def test_no_save_schema_before_reading_reduces_payload():
    class Provider(AnthropicProvider):
        async def message(self,messages,system,tools):
            assert 'save_finding' not in {t['name'] for t in tools}
            assert len(json.dumps(tools)) < len(json.dumps(TOOLS)) / 2
            return {'content':[{'type':'tool_use','name':'finish','input':{}}]}
    asyncio.run(Provider('fake','fake').decide({'scope_approved':True,'mission':{'domains':['example.com']}}))


def test_search_links_survive_history_rollover(tmp_path):
    class Provider:
        contexts=[]
        async def search(self,*args):
            return [{'url':'https://example.com/a','title':'A'}, {'url':'https://example.com/b','title':'B'}], {}
        async def decide(self,ctx):
            self.contexts.append(ctx)
            if not ctx['scope_approved']: return 'accept_scope',{},{}
            return 'finish',{},{}
    async def run():
        s=Store(tmp_path/'db')
        try:
            mid=s.create(MissionInput(subject='Veille documentaire',domains=['example.com'],action_budget=20))
            p=Provider();e=Engine(s,p)
            await e.execute(mid,'search_web',{'query':'veille','k':2},None)
            d=s.get(mid);d['sources']=[{'url':'https://example.com/a','error':'unavailable'}];s.save(d,'fixture',{})
            await e.run(mid)
            assert p.contexts[-1]['recent_results'] == []
            assert p.contexts[-1]['available_sources'] == [{'url':'https://example.com/b'}]
        finally: s.db.close()
    asyncio.run(run())


def test_context_excerpts_are_compact_exact_and_still_verifiable():
    from app.agent.evidence import passages, context_passages
    page = {'source_id':'one', 'text':('Navigation et conditions générales. ' * 70) +
            ('Nouveauté agents frameworks version disponible. ' * 40)}
    compact = context_passages(page,'Nouveautés frameworks agents')
    original = passages(page)
    assert len(compact) == 4 and all(p in original for p in compact)
    assert any('frameworks' in p['quote'] for p in compact)
    assert sum(len(p['quote']) for p in compact) <= 1800
    assert context_passages(page,'Nouveautés frameworks agents') == compact


def test_failed_finalization_does_not_buy_an_unaffordable_retry(tmp_path):
    class Provider:
        calls = 0
        async def decide(self, ctx):
            self.calls += 1
            if not ctx['scope_approved']:
                return 'accept_scope', {}, {'input_tokens':0,'output_tokens':0}
            return 'save_finding', {'finding':'malformed'}, {'input_tokens':6000,'output_tokens':0}
    async def run():
        s=Store(tmp_path/'db')
        try:
            mid=s.create(MissionInput(subject='Veille documentaire',auto_sources=True,action_budget=20))
            d=s.get(mid);d['domains']=['example.com'];d['model_calls_used']=1
            d['pages']={'one':{'source_id':'one','url':'https://example.com','text':'Un extrait vérifiable.'}}
            s.save(d,'model_finished',{'usage':{'input_tokens':31000,'output_tokens':0}})
            p=Provider();await Engine(s,p).run(mid)
            state=s.snapshot(mid)
            assert p.calls==2 and state['status']=='budget_exhausted'
            assert not state['findings']
            assert any(e['kind']=='finalization_retry_skipped' for e in state['events'])
        finally: s.db.close()
    asyncio.run(run())


def test_expensive_second_native_search_is_not_sent(tmp_path):
    from app.agent.budget import additional_web_search_fits
    from app.agent.web import ToolFailure
    import pytest
    events=[{'kind':'model_finished','data':{'usage':{
        'input_tokens':10000,'output_tokens':800,'server_tool_use':{'web_search_requests':1}}}},
        {'kind':'model_finished','data':{'proposed_action':'read_page',
         'usage':{'input_tokens':22000,'output_tokens':0}}}]
    assert not additional_web_search_fits(events,40000)
    class Provider:
        async def search(self,*args): raise AssertionError('Paid search must not be sent')
    async def run():
        s=Store(tmp_path/'db')
        try:
            mid=s.create(MissionInput(subject='Veille',domains=['example.com'],action_budget=20))
            for e in events: s.save(s.get(mid),e['kind'],e['data'])
            with pytest.raises(ToolFailure,match='web_search_budget_reserved'):
                await Engine(s,Provider()).execute(mid,'search_web',{'query':'veille','k':2},None)
            assert s.get(mid)['web_search_calls_used']==0
            assert s.events(mid)[-1]['kind']=='web_search_skipped'
        finally: s.db.close()
    asyncio.run(run())
