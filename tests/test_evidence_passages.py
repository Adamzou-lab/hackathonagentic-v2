import asyncio
import pytest
from pydantic import ValidationError
from app.agent.evidence import passages
from app.agent.engine import Engine
from app.agent.provider import AnthropicProvider
from app.agent.web import ToolFailure
from app.schemas import Evidence, MissionInput, SaveInput
from app.storage import Store

PAGE = {'source_id':'source-a','url':'https://example.com/news','title':'Version',
        'published_at':None,'text':'Une version apporte un outil de recherche documenté. '*60}

def test_passages_are_bounded_exact_and_source_specific():
    items = passages(PAGE)
    assert 1 < len(items) <= 24
    assert all(10 <= len(p['quote']) <= 450 and p['quote'] in PAGE['text'] for p in items)
    assert passages(PAGE) == items
    assert passages({**PAGE,'source_id':'source-b'})[0]['passage_id'] != items[0]['passage_id']

@pytest.mark.parametrize('reference', [{}, {'quote':'Citation exacte ici','passage_id':'x'*20}])
def test_evidence_requires_one_unambiguous_reference(reference):
    with pytest.raises(ValidationError): Evidence(source_id='source-a', **reference)

def test_passage_saved_as_exact_quote_and_forgery_rejected(tmp_path):
    store = Store(str(tmp_path/'db'))
    try:
        mid = store.create(MissionInput(subject='Veille outils IA', domains=['example.com']))
        data = store.get(mid); data['pages'] = {'source-a':PAGE}; store.save(data,'fixture',{})
        item = passages(PAGE)[0]
        def draft(pid, source='source-a'):
            return SaveInput(finding={'title':'Nouvel outil','summary':'Un outil de recherche est documenté.',
                'developer_impact':'Consulter la documentation.',
                'evidence':[{'source_id':source,'passage_id':pid}]},idempotency_key='one')
        engine=Engine(store,object())
        for bad in [draft('0'*20), draft(item['passage_id'],'unknown')]:
            with pytest.raises(ToolFailure,match='invalid_evidence'): engine.save_finding(mid,bad)
        assert store.get(mid)['findings'] == []
        engine.save_finding(mid,draft(item['passage_id']))
        ev=store.snapshot(mid)['findings'][0]['evidence'][0]
        assert ev == {'source_id':'source-a','quote':item['quote']}
    finally: store.db.close()

def test_last_actions_keep_model_choice_but_reserve_saving():
    class Recording(AnthropicProvider):
        async def message(self, messages, system, tools):
            assert {t['name'] for t in tools} == {'save_finding','finish','refuse'}
            return {'content':[{'type':'tool_use','name':'finish','input':{}}]}
    result=asyncio.run(Recording('fixture','fixture').decide({'scope_approved':True,
        'mission':{'domains':['example.com']},'evidence_catalog':[PAGE], 'actions_remaining':2}))
    assert result[0] == 'finish'

def test_budget_empty_message_distinguishes_incomplete_research(tmp_path):
    store = Store(str(tmp_path/'db'))
    try:
        mid=store.create(MissionInput(subject='Veille outils IA',domains=['example.com']))
        store.finish(mid,'budget_exhausted')
        assert 'Budget épuisé avant la sauvegarde' in store.snapshot(mid)['summary']['text']
    finally: store.db.close()

def test_repeated_page_uses_stored_content_without_network(tmp_path):
    class Reader:
        calls=0
        async def read(self,url,domains):
            self.calls+=1
            return {**PAGE,'status':'ok','error':None}
    async def scenario():
        store=Store(str(tmp_path/'reuse.db'))
        try:
            mid=store.create(MissionInput(subject='Veille outils IA',domains=['example.com']))
            engine=Engine(store,object()); reader=Reader()
            first=await engine.execute(mid,'read_page',{'url':PAGE['url']},reader)
            second=await engine.execute(mid,'read_page',{'url':PAGE['url']},reader)
            assert first==second and reader.calls==1
            assert any(e['kind']=='page_reused' for e in store.events(mid))
        finally: store.db.close()
    asyncio.run(scenario())

def test_short_watch_stops_research_after_target_is_saved():
    class Recording(AnthropicProvider):
        async def message(self, messages, system, tools):
            assert {t['name'] for t in tools} == {'finish','refuse'}
            return {'content':[{'type':'tool_use','name':'finish','input':{}}]}
    result=asyncio.run(Recording('fixture','fixture').decide({'scope_approved':True,
        'mission':{'domains':['example.com']},'finding_target':2,
        'saved_findings':[{'title':'Un'},{'title':'Deux'}],'actions_remaining':5}))
    assert result[0]=='finish'
