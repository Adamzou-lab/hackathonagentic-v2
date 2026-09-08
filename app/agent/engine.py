import asyncio
import hashlib
import json
import time
import aiohttp
from datetime import datetime, timedelta
from pydantic import ValidationError

from app.schemas import SearchInput, ReadInput, SaveInput
from app.storage import TERMINAL
from app.storage.watches import finding_key
from app.agent.discovery import DiscoveryInput, SelectionInput, normalize_candidate_url
from app.agent.web import WebReader, ToolFailure, check_url, PublicResolver


class Halt(Exception):
    def __init__(self, status):
        self.status = status


class Engine:
    def __init__(self, store, provider, reader_factory=WebReader):
        self.store, self.provider = store, provider
        self.reader_factory = reader_factory
        self.tasks = {}
        self.disabled_tools = frozenset()

    def finish_pending_action(self, mid, code):
        """Fermer aussi la trace d'un outil interrompu, sans exposer l'exception."""
        d = self.store.get(mid)
        if d.get('current_action') is not None:
            name = d['current_action']
            d['current_action'] = None
            d['had_errors'] = True
            self.store.save(d, 'action_finished', {'tool':name,
                'action_number':d['actions_used'], 'result':{'error':code}})

    def active(self):
        return any(not t.done() for t in self.tasks.values())

    def launch(self, mid):
        task = asyncio.create_task(self.run(mid))
        self.tasks[mid] = task
        def completed(task):
            if task.cancelled():
                # Cancellation before the coroutine's first instruction bypasses its try/finally.
                self.store.finish(mid, 'stopped' if self.store.get(mid)['status'] == 'stopping' else 'failed')
        task.add_done_callback(completed)

    def guard(self, mid):
        d = self.store.get(mid)
        if d['status'] in TERMINAL or d['status'] == 'stopping':
            raise Halt('stopped')
        if time.time() >= d['started_epoch'] + d['duration_minutes'] * 60:
            raise Halt('deadline_reached')
        return d

    def reserve(self, mid, counter, limit, kind):
        d = self.guard(mid)
        if d[counter] >= limit:
            raise Halt('budget_exhausted')
        d[counter] += 1
        self.store.save(d, kind, {counter:d[counter]})

    async def call(self, mid, awaitable, timeout=15):
        d = self.store.get(mid)
        left = d['started_epoch']+d['duration_minutes']*60-time.time()
        try:
            async with asyncio.timeout(max(0.001, min(timeout, left))):
                return await awaitable
        except TimeoutError:
            self.guard(mid)
            raise ToolFailure('timeout')

    def stop(self, mid):
        d = self.store.get(mid)
        if d['status'] not in TERMINAL and d['status'] != 'stopping':
            d['status'] = 'stopping'
            self.store.save(d, 'stop_requested', {})
            task = self.tasks.get(mid)
            if task:
                task.cancel()
            else:
                self.store.finish(mid, 'stopped')

    def save_finding(self, mid, args):
        d = self.guard(mid)
        finding = args.finding.model_dump()
        for ev in finding['evidence']:
            page = d['pages'].get(ev['source_id'])
            if not page or ev['quote'] not in page['text']:
                raise ToolFailure('invalid_evidence')
        # Dates are untrusted until backed by a publication field on a cited page.
        available = [d['pages'][e['source_id']].get('published_at') for e in finding['evidence']]
        date = finding['event_date']
        if not date or not any(x and x[:10] == date[:10] for x in available):
            finding.update(event_date=None, date_status='unknown')
        else:
            try:
                day = datetime.fromisoformat(date[:10]).date()
                end = datetime.fromisoformat(d['created_at']).date()
                start = datetime.fromisoformat(d['update_since']).date() if d.get('update_since') else end-timedelta(days=7)
                finding['date_status'] = 'in_window' if start <= day <= end else 'outside_window'
            except ValueError:
                finding.update(event_date=None, date_status='unknown')
        if len({e['source_id'] for e in finding['evidence']}) < 2:
            finding['confidence'] = 'single_source'
        prior = self.store.watch(d['watch_id'])['findings'] if d.get('watch_id') else []
        known = {f['entry_id']:f for f in prior if f['mission_id'] != mid}
        change, related = args.change, args.related_finding_id
        if related and related not in {f['entry_id'] for f in d.get('known_findings',[])}:
            raise ToolFailure('unknown_related_finding')
        links = [{'url':d['pages'][e['source_id']]['url'],'quote':e['quote']} for e in finding['evidence']]
        key = finding_key(finding, links)
        duplicate = next((f for f in known.values() if finding_key(f, f['source_links']) == key), None)
        if duplicate:
            change, related = 'duplicate', duplicate['entry_id']
        if change == 'duplicate':
            # Le rapprochement sémantique proposé reste tracé ; rien n'efface l'ancien constat.
            if related not in known:
                raise ToolFailure('unknown_related_finding')
        finding.update(change=change, related_finding_id=related)
        fingerprint = hashlib.sha256(json.dumps(finding, sort_keys=True).encode()).hexdigest()
        old = d['keys'].get(args.idempotency_key)
        if old and old != fingerprint:
            raise ToolFailure('idempotency_conflict')
        existing = next((f for f in d['findings'] if f['finding_id'] == fingerprint[:24]), None)
        if change == 'update' and related not in known and not existing:
            raise ToolFailure('related_finding_superseded')
        d['keys'][args.idempotency_key] = fingerprint
        if not existing and change != 'duplicate':
            d['findings'].append(dict(finding_id=fingerprint[:24], **finding))
        result = {'finding_id': fingerprint[:24], 'disposition':'already_saved' if existing else 'created'}
        if change == 'duplicate':
            result.update(disposition='already_known', related_finding_id=related)
        elif change == 'update':
            result.update(disposition='updated' if not existing else 'already_saved', related_finding_id=related)
        self.store.save(d, 'finding_unchanged' if change == 'duplicate' else ('finding_updated' if change == 'update' else 'finding_saved'), result)
        return result

    async def execute(self, mid, name, raw, reader):
        if name in self.disabled_tools:
            raise ToolFailure('tool_disabled_for_test')
        d = self.guard(mid)
        if name in {'search_web','read_page','save_finding'} and not d['domains']:
            raise ToolFailure('sources_not_selected')
        if name == 'discover_sources':
            args = DiscoveryInput.model_validate(raw)
            if not d.get('auto_sources') or d['domains'] or d.get('discovery_attempted'):
                raise ToolFailure('source_discovery_not_allowed')
            d['discovery_attempted'] = True
            self.store.save(d, 'source_discovery_started', {'query':args.query})
            self.reserve(mid, 'model_calls_used', 60, 'model_started')
            self.reserve(mid, 'network_requests_used', 200, 'network_started')
            candidates, usage = await self.call(mid, self.provider.discover_sources(args.query), timeout=45)
            checked = []
            for candidate in candidates[:10]:
                domain, url = normalize_candidate_url(candidate['url'])
                if domain not in [c['domain'] for c in checked]:
                    checked.append({'domain':domain,'url':url,'title':str(candidate.get('title',''))[:200]})
            if not checked:
                raise ToolFailure('source_discovery_no_candidates')
            d = self.guard(mid)
            d['source_candidates'] = checked
            self.store.save(d, 'model_finished', {'usage':usage})
            return checked
        if name == 'select_sources':
            args = SelectionInput.model_validate(raw)
            candidates = {c['domain']:c for c in d.get('source_candidates',[])}
            if not d.get('auto_sources') or d['domains'] or not candidates:
                raise ToolFailure('source_selection_not_allowed')
            if any(source.domain not in candidates for source in args.sources):
                raise ToolFailure('source_not_discovered')
            resolver = PublicResolver()
            try:
                for source in args.sources:
                    self.reserve(mid,'network_requests_used',200,'network_started')
                    await self.call(mid,resolver.resolve(source.domain,443))
            except OSError as exc:
                raise ToolFailure('source_dns_unavailable') from exc
            finally:
                await resolver.close()
            d = self.guard(mid)
            d['domains'] = [source.domain for source in args.sources]
            d['selected_sources'] = [source.model_dump() | {'url':candidates[source.domain]['url']} for source in args.sources]
            # Les anciennes sources non retenues ne sont pas réinjectées ensuite.
            from urllib.parse import urlsplit
            d['known_findings'] = [f for f in d.get('known_findings',[]) if
                all(urlsplit(url).hostname in d['domains'] for url in f.get('urls',[]))]
            self.store.save(d, 'sources_selected', {'sources':d['selected_sources'], 'known_findings_count':len(d['known_findings'])})
            return d['selected_sources']
        if name == 'search_web':
            args = SearchInput.model_validate(raw)
            self.reserve(mid, 'model_calls_used', 60, 'model_started')
            self.reserve(mid, 'network_requests_used', 200, 'network_started')
            result, usage = await self.call(mid, self.provider.search(args.query, args.k, self.guard(mid)['domains']), timeout=45)
            d = self.guard(mid)
            self.store.save(d, 'model_finished', {'usage':usage})
            return result
        if name == 'read_page':
            args = ReadInput.model_validate(raw)
            d = self.guard(mid)
            url = check_url(args.url, d['domains'])
            if d['attempts'].get(url, 0) >= 2:
                raise ToolFailure('attempts_exhausted')
            d['attempts'][url] = d['attempts'].get(url, 0) + 1
            self.store.save(d, 'page_attempt', {'url':url, 'attempt':d['attempts'][url]})
            try:
                page = await self.call(mid, reader.read(url, d['domains']))
            except (aiohttp.ClientError, OSError) as exc:
                raise ToolFailure('unavailable') from exc
            d = self.guard(mid)
            d['pages'][page['source_id']] = page
            d['sources'] = [s for s in d['sources'] if s.get('url') != url]
            d['sources'].append({k:v for k,v in page.items() if k != 'text'})
            self.store.save(d, 'page_saved', {'source_id':page['source_id'], 'url':url})
            return page
        if name == 'save_finding':
            return self.save_finding(mid, SaveInput.model_validate(raw))
        raise ToolFailure('unknown_tool')

    async def run(self, mid):
        history = []
        scope_approved = False
        reader = self.reader_factory(lambda: self.reserve(mid, 'network_requests_used', 200, 'network_started'))
        try:
            d = self.guard(mid)
            d['status'] = 'running'
            self.store.save(d, 'started', {})
            while True:
                d = self.guard(mid)
                if d['actions_used'] >= d['action_budget']:
                    raise Halt('budget_exhausted')
                self.reserve(mid, 'model_calls_used', 60, 'model_started')
                self.reserve(mid, 'network_requests_used', 200, 'network_started')
                context = {'scope_approved':scope_approved, 'mission':{k:d.get(k) for k in ['subject','domains','created_at','auto_sources']},
                           'source_candidates':d.get('source_candidates',[]),
                           'known_findings':d.get('known_findings',[]),
                           'known_findings_truncated':d.get('known_findings_truncated',False),
                           'update_since':d.get('update_since'),
                           'actions_remaining':d['action_budget']-d['actions_used'],
                           'saved_findings':[{'title':f['title'], 'finding_id':f['finding_id']} for f in d['findings']],
                           'recent_results':history[-4:]}
                name, raw, usage = await self.call(mid, self.provider.decide(context), timeout=45)
                d = self.guard(mid)
                self.store.save(d, 'model_finished', {'usage':usage, 'proposed_action':name})
                if name == 'refuse' or (not scope_approved and (name != 'accept_scope' or raw != {})):
                    reasons = {
                        'out_of_scope': 'Lockin réalise des veilles documentaires sur des sources publiques. Cette demande sort de ce cadre.',
                        'unsafe_request': 'Cette demande exige une action ou un accès non autorisé. Reformulez une demande de veille sur des sources publiques.',
                        'clarification_required': 'Le périmètre de cette demande ne peut pas être validé. Précisez le sujet de veille et les informations recherchées.'}
                    code = raw.get('code') if isinstance(raw, dict) and set(raw) == {'code'} else None
                    code = code if isinstance(code, str) and code in reasons else 'clarification_required'
                    d['refusal_reason'] = reasons[code]
                    self.store.save(d, 'mission_refused', {'code':code, 'reason':reasons[code]})
                    self.store.finish(mid, 'refused')
                    return
                if name == 'accept_scope':
                    if scope_approved or raw != {}:
                        raise ToolFailure('invalid_scope_decision')
                    scope_approved = True
                    self.store.save(d, 'scope_accepted', {})
                    continue
                if name == 'finish':
                    if not d['domains']:
                        raise ToolFailure('sources_not_selected')
                    if raw:
                        raise ToolFailure('invalid_finish')
                    self.store.finish(mid, 'completed')
                    return
                self.reserve(mid, 'actions_used', d['action_budget'], 'action_reserved')
                d = self.guard(mid)
                d['current_action'] = name
                # Only schema-valid, bounded parameters enter the journal.
                schema = {'discover_sources':DiscoveryInput, 'select_sources':SelectionInput, 'search_web':SearchInput, 'read_page':ReadInput, 'save_finding':SaveInput}.get(name)
                try:
                    parameters = schema.model_validate(raw).model_dump() if schema else {}
                except ValidationError:
                    parameters = {'validation':'invalid_input'}
                self.store.save(d, 'action_started', {'tool':name, 'action_number':d['actions_used'], 'parameters':parameters})
                fatal = None
                try:
                    result = await self.execute(mid, name, raw, reader)
                except (Halt, asyncio.CancelledError):
                    raise
                except Exception as exc:
                    code = exc.code if isinstance(exc, ToolFailure) else ('invalid_input' if isinstance(exc, ValidationError) else 'execution_error')
                    result = {'error': code}
                    d = self.guard(mid)
                    d['had_errors'] = True
                    if name == 'read_page' and isinstance(raw, dict) and isinstance(raw.get('url'), str):
                        try:
                            url = check_url(raw['url'], d['domains'])
                            d['sources'].append({'url':url, 'status':'error', 'error':code, 'source_id':None})
                        except ToolFailure:
                            pass
                    self.store.save(d, 'tool_error', {'tool':name, 'code':code})
                    if name == 'discover_sources' or code.startswith(('anthropic_http_', 'source_discovery_')) or code in {'web_search_unavailable', 'execution_error'}:
                        fatal = code
                d = self.guard(mid)
                d['current_action'] = None
                self.store.save(d, 'action_finished', {'tool':name, 'action_number':d['actions_used'], 'result':result if name != 'read_page' else
                                {k:v for k,v in result.items() if k != 'text'}})
                if fatal:
                    raise ToolFailure(fatal)
                # Bound context even when recent results contain large pages.
                history.append({'tool':name, 'result':result})
        except asyncio.CancelledError:
            self.finish_pending_action(mid, 'cancelled')
            self.store.finish(mid, 'stopped' if self.store.get(mid)['status'] == 'stopping' else 'failed',
                              None if self.store.get(mid)['status'] == 'stopping' else 'Processus arrêté.')
        except Halt as halt:
            self.finish_pending_action(mid, halt.status)
            self.store.finish(mid, halt.status)
        except Exception as exc:
            # Never return upstream exception strings, headers, credentials or response bodies.
            code = exc.code if isinstance(exc, ToolFailure) else 'execution_error'
            self.finish_pending_action(mid, code)
            self.store.finish(mid, 'failed', code)

    async def close(self):
        tasks = [t for t in self.tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
