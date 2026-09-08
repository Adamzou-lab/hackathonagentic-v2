"""Réponses incomplètes et absence de preuve d'outil, sans réseau ni crédit IA."""
import asyncio
import json

import httpx
import pytest

from app.agent.engine import Engine
from app.agent.provider import AnthropicProvider
from app.agent.web import ToolFailure
from app.schemas import MissionInput
from app.storage import Store


def tool(name='accept_scope', arguments=None):
    return {'type':'tool_use', 'name':name, 'input':arguments or {}}


def response(content, stop_reason='tool_use'):
    return {'content':content, 'stop_reason':stop_reason,
            'usage':{'input_tokens':4, 'output_tokens':2}}


def streaming_response(block, stop_reason='tool_use', raw=None):
    chunks = [
        {'type':'message_start', 'message':{'usage':{'input_tokens':4}}},
        {'type':'content_block_start', 'index':0,
         'content_block':{**block, 'input':{}}},
        {'type':'content_block_delta', 'index':0,
         'delta':{'type':'input_json_delta',
                  'partial_json':json.dumps(block['input']) if raw is None else raw}},
        {'type':'content_block_stop', 'index':0},
        {'type':'message_delta', 'delta':{'stop_reason':stop_reason},
         'usage':{'output_tokens':2}},
        {'type':'message_stop'},
    ]
    return httpx.Response(200, headers={'content-type':'text/event-stream'},
                          text=''.join('data: '+json.dumps(chunk)+'\n\n' for chunk in chunks))


def mock_transport(monkeypatch, make_response):
    original = httpx.AsyncClient
    calls = []

    def handle(request):
        calls.append(request)
        return make_response(request)

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr('app.agent.provider.httpx.AsyncClient',
                        lambda **kwargs: original(transport=transport, **kwargs))
    return calls


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('reason', ['max_tokens', 'pause_turn', 'stop_sequence'])
def test_incomplete_decision_fails_without_tool_or_retry(tmp_path, monkeypatch, streaming, reason):
    calls = mock_transport(monkeypatch, lambda request:
        streaming_response(tool(), reason) if streaming
        else httpx.Response(200, json=response([tool()], reason)))

    async def scenario():
        store = Store(str(tmp_path/'incomplete.db'))
        provider = AnthropicProvider('fixture-key', 'fixture-model', broker=object() if streaming else None)
        engine = Engine(store, provider)
        try:
            mid = store.create(MissionInput(subject='Nouveautés documentaires', domains=['example.com']))
            await engine.run(mid)
            state = store.snapshot(mid)
            assert state['status'] == 'failed'
            assert state['error'] == 'anthropic_incomplete_response'
            assert state['actions_used'] == 0
            assert not [event for event in state['events'] if event['kind'] in {'action_started', 'mission_refused'}]
            failures = [event for event in state['events'] if event['kind'] == 'dependency_failed']
            assert len(failures) == 1
            assert failures[0]['data']['dependency'] == 'model_provider'
            assert failures[0]['data']['operation'] == 'decide'
            assert failures[0]['data']['reaction'] == 'stop'
            assert len(calls) == 1
        finally:
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('reason', [None, [], 'unexpected-stop'])
def test_missing_or_unknown_final_reason_is_not_a_complete_response(monkeypatch, reason):
    calls = mock_transport(monkeypatch, lambda request:httpx.Response(200, json=response([tool()], reason)))
    with pytest.raises(ToolFailure, match='^anthropic_incomplete_response$'):
        asyncio.run(AnthropicProvider('fixture-key','fixture-model').decide({}))
    assert len(calls) == 1


def test_truncated_stream_is_provider_failure_not_user_refusal(tmp_path, monkeypatch):
    calls = mock_transport(monkeypatch, lambda request:streaming_response(tool(), raw='{"unfinished":'))

    async def scenario():
        store = Store(str(tmp_path/'truncated.db'))
        engine = Engine(store, AnthropicProvider('fixture-key','fixture-model',broker=object()))
        try:
            mid = store.create(MissionInput(subject='Nouveautés documentaires',domains=['example.com']))
            await engine.run(mid)
            state = store.snapshot(mid)
            assert state['status'] == 'failed'
            assert state['error'] == 'anthropic_invalid_response'
            assert state.get('refusal_reason') is None
            assert not [event for event in state['events'] if event['kind'] in {'action_started','mission_refused'}]
            failure = next(event for event in state['events'] if event['kind'] == 'dependency_failed')
            assert failure['data']['dependency'] == 'model_provider'
            assert failure['data']['reaction'] == 'stop'
            assert len(calls) == 1
        finally:
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


def test_truncated_adapter_output_is_never_user_ambiguity():
    class Adapter(AnthropicProvider):
        async def message(self, *args):
            return response([{**tool(), 'truncated':True}])

    with pytest.raises(ToolFailure, match='^anthropic_invalid_response$'):
        asyncio.run(Adapter('fixture','fixture').decide({}))


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('code', ['out_of_scope','unsafe_request','clarification_required'])
def test_real_refusal_action_remains_a_refusal(monkeypatch, streaming, code):
    block = tool('refuse', {'code':code})
    calls = mock_transport(monkeypatch, lambda request:
        streaming_response(block) if streaming
        else httpx.Response(200, json=response([block])))
    provider = AnthropicProvider('fixture-key','fixture-model',broker=object() if streaming else None)
    action, arguments, usage = asyncio.run(provider.decide({'scope_approved':False}))
    assert (action, arguments) == ('refuse', {'code':code})
    assert usage == {'input_tokens':4,'output_tokens':2}
    assert len(calls) == 1


@pytest.mark.parametrize('blocks', [[], [{'type':'text','text':'I searched for this.'}]])
def test_search_requires_an_actual_tool_result(monkeypatch, blocks):
    calls = mock_transport(monkeypatch, lambda request:httpx.Response(200, json=response(blocks,'end_turn')))
    with pytest.raises(ToolFailure, match='^web_search_unavailable$'):
        asyncio.run(AnthropicProvider('fixture-key','fixture-model').search('subject',2,['example.com']))
    assert len(calls) == 1


def test_actual_empty_search_result_is_a_valid_zero_hits(monkeypatch):
    blocks = [{'type':'web_search_tool_result','content':[]}]
    calls = mock_transport(monkeypatch, lambda request:httpx.Response(200, json=response(blocks,'end_turn')))
    hits, usage = asyncio.run(AnthropicProvider('fixture-key','fixture-model').search('subject',2,['example.com']))
    assert hits == []
    assert usage == {'input_tokens':4,'output_tokens':2}
    assert len(calls) == 1


@pytest.mark.parametrize('actual_result', [False, True])
def test_engine_stops_on_missing_search_proof_but_accepts_real_empty_result(tmp_path, monkeypatch, actual_result):
    replies = [
        response([tool()]),
        response([tool('search_web', {'query':'subject','k':2})]),
        response([{'type':'web_search_tool_result','content':[]}] if actual_result
                 else [{'type':'text','text':'No tool call.'}], 'end_turn'),
    ]
    if actual_result:
        replies.append(response([tool('finish')]))

    def reply(request):
        assert replies, 'Appel fournisseur supplémentaire inattendu'
        return httpx.Response(200, json=replies.pop(0))

    calls = mock_transport(monkeypatch, reply)

    async def scenario():
        store = Store(str(tmp_path/'search-proof.db'))
        engine = Engine(store, AnthropicProvider('fixture-key','fixture-model'))
        try:
            mid = store.create(MissionInput(subject='Nouveautés documentaires',domains=['example.com']))
            await engine.run(mid)
            state = store.snapshot(mid)
            assert state['status'] == ('completed' if actual_result else 'failed')
            assert state['error'] == (None if actual_result else 'web_search_unavailable')
            assert len(calls) == (4 if actual_result else 3)
            assert replies == []
            failures = [event for event in state['events'] if event['kind'] == 'dependency_failed']
            if actual_result:
                assert failures == []
            else:
                assert len(failures) == 1
                assert failures[0]['data']['operation'] == 'search_web'
                assert failures[0]['data']['reaction'] == 'stop'
        finally:
            await engine.close()
            store.db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('code', ['unavailable','too_many_requests',['private-detail']])
def test_hits_do_not_hide_a_provider_failure(monkeypatch, code):
    blocks = [
        {'type':'web_search_tool_result','content':[
            {'type':'web_search_result','url':'https://example.com/news','title':'Publication'}]},
        {'type':'web_search_tool_result','content':{'error_code':code}},
    ]
    calls = mock_transport(monkeypatch, lambda request:httpx.Response(200, json=response(blocks,'end_turn')))
    expected = code if isinstance(code,str) else 'unavailable'
    with pytest.raises(ToolFailure, match='^web_search_'+expected+'$'):
        asyncio.run(AnthropicProvider('fixture-key','fixture-model').search('subject',2,['example.com']))
    assert len(calls) == 1


@pytest.mark.parametrize('content', [None, ['malformed'], [{'type':'text','text':'not a search result'}]])
def test_malformed_tool_result_is_never_empty_success(monkeypatch, content):
    blocks = [{'type':'web_search_tool_result','content':content}]
    calls = mock_transport(monkeypatch, lambda request:httpx.Response(200, json=response(blocks,'end_turn')))
    with pytest.raises(ToolFailure):
        asyncio.run(AnthropicProvider('fixture-key','fixture-model').search('subject',2,['example.com']))
    assert len(calls) == 1
