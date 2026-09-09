"""Choix de sources et parsing strict, sans appel API ni requête DNS."""
import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.agent.discovery import (DiscoveryInput, SelectionInput, extract_candidates,
                                 normalize_candidate_url)
from app.agent.provider import AnthropicProvider
from app.agent.web import ToolFailure


def search_result(*urls):
    return {'content': [{'type': 'web_search_tool_result', 'content': [
        {'type': 'web_search_result', 'url': url, 'title': 'Publication d’origine'}
        for url in urls]}], 'usage': {'input_tokens': 12, 'output_tokens': 7}}


@pytest.mark.parametrize('url', [
    'http://example.com/page', 'https://127.0.0.1/', 'https://[::1]/',
    'https://localhost/', 'https://sub.localhost/', 'https://editor.local/',
    'https://site.internal/', 'https://site.test/', 'https://router.home.arpa/',
    'https://secret.onion/', 'https://example.com:8443/',
    'https://user:pass@example.com/', 'https://@example.com/',
    'https://example.com\\@127.0.0.1/', 'https://example.com/\nsecret',
    'https://example.com/a b', 'https://example.com:invalid/',
    'https://%31%32%37.0.0.1/', 'https:///page', None, 123,
])
def test_discovery_rejects_ambiguous_or_non_public_urls(url):
    with pytest.raises(ToolFailure, match='^blocked_url$'):
        normalize_candidate_url(url)


def test_discovery_normalizes_host_default_port_and_fragment():
    assert normalize_candidate_url('https://WWW.Example.COM.:443/news?q=1#section') == (
        'www.example.com', 'https://www.example.com/news?q=1')
    assert normalize_candidate_url('https://bücher.de') == (
        'xn--bcher-kva.de', 'https://xn--bcher-kva.de/')


def test_candidates_deduplicate_by_domain_and_are_bounded():
    response = search_result('https://www.example.com/one',
        'https://WWW.example.com:443/two#section', 'http://private.local/',
        *(f'https://source{i}.org/news' for i in range(15)))
    candidates = extract_candidates(response)
    assert len(candidates) == 10
    assert len({item['domain'] for item in candidates}) == 10
    assert candidates[0] == {'domain': 'www.example.com',
        'url': 'https://www.example.com/one', 'title': 'Publication d’origine'}


def test_candidates_ignore_free_text_and_bound_untrusted_title():
    response = search_result('https://source.org/news')
    response['content'].insert(0, {'type': 'text', 'text': 'https://fake.org'})
    response['content'][1]['content'][0]['title'] = 'x' * 1000
    candidates = extract_candidates(response)
    assert len(candidates) == 1 and len(candidates[0]['title']) == 200


@pytest.mark.parametrize('response, code', [
    ({'content': []}, 'source_discovery_no_candidates'),
    (search_result('http://source.org/'), 'source_discovery_no_candidates'),
    ({'content': [{'type': 'text', 'text': 'https://source.org'}]},
     'source_discovery_no_candidates'),
    ({}, 'source_discovery_invalid_response'),
    ([], 'source_discovery_invalid_response'),
    ({'content': [{'type': 'web_search_tool_result', 'content': {
        'type': 'web_search_tool_result_error', 'error_code': 'too_many_requests'}}]},
     'source_discovery_too_many_requests'),
    ({'content': [{'type': 'web_search_tool_result', 'content': {
        'error_code': ['malformed']}}]}, 'source_discovery_unavailable'),
])
def test_discovery_errors_are_explicit_and_safe(response, code):
    with pytest.raises(ToolFailure) as exc:
        extract_candidates(response)
    assert exc.value.code == code


def test_discovery_failure_does_not_silently_accept_partial_success():
    response = search_result('https://source.org/')
    response['content'].append({'type': 'web_search_tool_result', 'content': {
        'type': 'web_search_tool_result_error', 'error_code': 'unavailable'}})
    with pytest.raises(ToolFailure, match='source_discovery_unavailable'):
        extract_candidates(response)


def test_discovery_keeps_successful_candidates_when_search_limit_is_then_reached():
    response = search_result('https://source.org/')
    response['content'].append({'type': 'web_search_tool_result', 'content': {
        'type': 'web_search_tool_result_error', 'error_code': 'max_uses_exceeded'}})
    assert extract_candidates(response) == [
        {'domain': 'source.org', 'url': 'https://source.org/', 'title': 'Publication d’origine'}]


def test_discovery_search_limit_without_valid_candidates_remains_an_error():
    response = search_result('https://localhost/')
    response['content'].append({'type': 'web_search_tool_result', 'content': {
        'type': 'web_search_tool_result_error', 'error_code': 'max_uses_exceeded'}})
    with pytest.raises(ToolFailure, match='^source_discovery_max_uses_exceeded$'):
        extract_candidates(response)


@pytest.mark.parametrize('approved, auto, domains, candidates, expected', [
    (False, True, [], [], {'accept_scope', 'refuse'}),
    (False, True, [], [{'domain': 'source.org'}], {'accept_scope', 'refuse'}),
    (True, True, [], [], {'discover_sources', 'refuse'}),
    (True, True, [], [{'domain': 'source.org'}], {'select_sources', 'refuse'}),
    (True, True, ['source.org'], [], {'search_web', 'read_page', 'finish', 'refuse'}),
    (True, False, ['source.org'], [], {'search_web', 'read_page', 'finish', 'refuse'}),
])
@pytest.mark.parametrize('streaming', [False, True])
def test_each_phase_exposes_only_its_model_choices(approved, auto, domains,
                                                 candidates, expected, streaming):
    class Recording(AnthropicProvider):
        def __init__(self):
            super().__init__('fake', 'fake', broker=object() if streaming else None)
            self.calls = []

        async def record(self, mode, messages, system, tools):
            self.calls.append((mode, messages, system, tools))
            return {'content': [{'type': 'tool_use', 'name': 'refuse',
                                 'input': {'code': 'clarification_required'}}]}

        async def message(self, *args):
            return await self.record('ordinary', *args)

        async def message_streaming(self, *args):
            return await self.record('streaming', *args)

    context = {'scope_approved': approved, 'mission': {'auto_sources': auto,
        'domains': domains, 'subject': 'Veille documentaire'}, 'source_candidates': candidates,
        'known_findings': [{'entry_id': 'finding-1', 'summary': 'Déjà connu'}],
        'update_since': '2026-09-01T12:00:00+00:00'}
    provider = Recording()
    asyncio.run(provider.decide(context))
    assert len(provider.calls) == 1, 'Pas de recherche cachée dans la décision'
    mode, messages, system, tools = provider.calls[0]
    assert mode == ('streaming' if streaming else 'ordinary')
    assert {tool['name'] for tool in tools} == expected
    payload = json.loads(messages[0]['content'])
    if approved and auto and not domains:
        assert payload == {k:context[k] for k in ('mission','source_candidates','update_since')}
        assert len(system) < 1800
    else:
        assert payload == (context if approved else {'mission': context['mission'], 'scope_approved': False})
    if approved and domains:
        assert 'known_findings' in system and 'related_finding_id' in system


def test_discovery_performs_exactly_one_search_call_and_keeps_usage():
    class Recording(AnthropicProvider):
        calls = 0
        async def message(self, messages, system, tools):
            self.calls += 1
            assert messages == [{'role': 'user', 'content': 'Sources PostgreSQL'}]
            assert tools == [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 1}]
            return search_result('https://www.postgresql.org/news/')
    provider = Recording('fake', 'fake')
    candidates, usage = asyncio.run(provider.discover_sources('Sources PostgreSQL'))
    assert provider.calls == 1
    assert candidates[0]['domain'] == 'www.postgresql.org'
    assert usage == {'input_tokens': 12, 'output_tokens': 7}


def test_discovery_network_failure_is_explicit_without_retry():
    class Failing(AnthropicProvider):
        calls = 0
        async def message(self, *args):
            self.calls += 1
            raise httpx.ReadTimeout('private details')
    provider = Failing('fake', 'fake')
    with pytest.raises(ToolFailure, match='^source_discovery_unavailable$'):
        asyncio.run(provider.discover_sources('Sources PostgreSQL'))
    assert provider.calls == 1


@pytest.mark.parametrize('query', ['', '   ', 'x' * 501, 3])
def test_discovery_input_is_bounded(query):
    with pytest.raises(ValidationError):
        DiscoveryInput(query=query)


@pytest.mark.parametrize('sources', [
    [], [{'domain': 'source.org', 'reason': 'primaire'}] * 2,
    [{'domain': f'source{i}.org', 'reason': 'primaire'} for i in range(6)],
    [{'domain': 'https://source.org', 'reason': 'primaire'}],
    [{'domain': 'source.org', 'reason': '   '}],
    [{'domain': 'source.org', 'reason': 'x' * 301}],
    [{'domain': 'source.org', 'reason': 'primaire', 'url': 'https://other.org'}],
])
def test_selection_requires_one_to_five_unique_domains_with_short_reasons(sources):
    with pytest.raises(ValidationError):
        SelectionInput(sources=sources)


def test_selection_normalizes_domains_but_does_not_invent_them():
    selected = SelectionInput(sources=[{'domain': 'WWW.Source.ORG.', 'reason': ' Site officiel '}])
    assert selected.model_dump() == {'sources': [{'domain': 'www.source.org', 'reason': 'Site officiel'}]}
