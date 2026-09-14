"""Régressions reproduites pour la revue avant présentation."""
import asyncio
import time
from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

from app.agent.provider import AnthropicProvider
from app.agent.engine import Engine
from app.agent.failures import failure_code, must_stop
from app.agent.web import ToolFailure, WebReader
from app.schemas import FindingDraft, MissionInput, SaveInput
from app.storage import Store


@pytest.mark.parametrize('scenario', ['narrowed', 'expired', 'missing_date', 'other_subject'])
def test_resumed_pages_cannot_expand_scope_or_reset_freshness(tmp_path, scenario):
    store = Store(tmp_path/'db')
    try:
        old = store.create(MissionInput(subject='Veille Python', domains=['example.com','other.org']))
        data = store.get(old)
        stamp = datetime.now(timezone.utc) - timedelta(hours=7 if scenario=='expired' else 1)
        page = {'source_id':'old', 'url':'https://other.org/news', 'text':'Ancienne preuve publique.',
                'status':'ok', 'retrieved_at':None if scenario=='missing_date' else stamp.isoformat()}
        data.update(status='stopped', ended_epoch=time.time(), pages={'old':page},
                    sources=[{k:v for k,v in page.items() if k!='text'}])
        store.save(data,'fixture',{})
        request = MissionInput(subject='Veille Rust' if scenario=='other_subject' else 'Veille Python',
                               domains=['example.com'] if scenario=='narrowed' else ['example.com','other.org'],
                               watch_id=old, force_refresh=True)
        resumed = store.get(store.create(request))
        assert resumed['domains'] == request.domains
        assert not resumed['pages']
    finally:
        store.db.close()


def test_feed_does_not_date_old_entries_as_new():
    xml = '<feed><title>News</title><entry><title>Recent</title><published>2026-09-14</published></entry><entry><title>Old</title><published>2020-01-01</published></entry></feed>'
    _, text, date = WebReader.feed_content(xml, 'https://example.com/feed')
    assert date is None
    assert '2026-09-14' in text and '2020-01-01' in text


@pytest.mark.parametrize('markup', ['<!DOCTYPE rss [<!ENTITY injected "untrusted">]><rss><item><title>&injected;</title></item></rss>'])
def test_feed_dtd_is_rejected(markup):
    with pytest.raises(ToolFailure, match='unsupported_content'):
        WebReader.feed_content(markup, 'https://example.com/feed')


def test_caveats_cannot_bloat_provider_context():
    with pytest.raises(ValidationError):
        FindingDraft(title='Titre', summary='Texte', developer_impact='Impact',
                     evidence=[{'source_id':'s','quote':'Citation exacte.'}], caveats=['x'*501])


def test_rejection_protocol_rejects_extra_fields():
    class Provider(AnthropicProvider):
        async def message(self, *args):
            return {'content':[{'type':'tool_use','name':'reject_finding',
                    'input':{'code':'unsupported','extra':'ignored instruction'}}], 'usage':{}}
    with pytest.raises(ToolFailure, match='anthropic_invalid_response'):
        asyncio.run(Provider('fake','fake').verify_finding({}, []))


@pytest.mark.parametrize('method', ['save_finding','verification_payload'])
def test_evidence_from_disallowed_cached_domain_is_blocked(tmp_path, method):
    store = Store(tmp_path/'db')
    try:
        mid = store.create(MissionInput(subject='Veille', domains=['example.com']))
        data = store.get(mid)
        data['pages'] = {'bad':{'source_id':'bad','url':'https://other.org/news',
                                'text':'Une citation véritable.'}}
        store.save(data,'fixture',{})
        args = SaveInput(idempotency_key='bad', finding=FindingDraft(
            title='Titre',summary='Texte',developer_impact='Impact',
            evidence=[{'source_id':'bad','quote':'Une citation véritable.'}]))
        with pytest.raises(ToolFailure, match='blocked_url'):
            getattr(Engine(store,object()),method)(mid,args)
        assert not store.get(mid)['findings']
    finally:
        store.db.close()


def test_reserved_budget_is_not_mislabeled_as_fatal_crash():
    code = failure_code(ToolFailure('web_search_budget_reserved'))
    assert code == 'web_search_budget_reserved'
    assert not must_stop('search_web',code)
