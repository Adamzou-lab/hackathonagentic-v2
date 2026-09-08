import asyncio
import hashlib
import json
import time
import aiohttp
from datetime import datetime, timedelta
from pydantic import ValidationError

from app.schemas import SearchInput, ReadInput, SaveInput
from app.storage import TERMINAL
from app.agent.web import WebReader, ToolFailure, check_url


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

    async def call(self, mid, awaitable):
        d = self.store.get(mid)
        left = d['started_epoch']+d['duration_minutes']*60-time.time()
        try:
            async with asyncio.timeout(max(0.001, min(15, left))):
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
                finding['date_status'] = 'in_window' if end-timedelta(days=7) <= day <= end else 'outside_window'
            except ValueError:
                finding.update(event_date=None, date_status='unknown')
        if len({e['source_id'] for e in finding['evidence']}) < 2:
            finding['confidence'] = 'single_source'
        fingerprint = hashlib.sha256(json.dumps(finding, sort_keys=True).encode()).hexdigest()
        old = d['keys'].get(args.idempotency_key)
        if old and old != fingerprint:
            raise ToolFailure('idempotency_conflict')
        existing = next((f for f in d['findings'] if f['finding_id'] == fingerprint[:24]), None)
        d['keys'][args.idempotency_key] = fingerprint
        if not existing:
            d['findings'].append(dict(finding_id=fingerprint[:24], **finding))
        result = {'finding_id': fingerprint[:24], 'disposition':'already_saved' if existing else 'created'}
        self.store.save(d, 'finding_saved', result)
        return result

    async def execute(self, mid, name, raw, reader):
        if name in self.disabled_tools:
            raise ToolFailure('tool_disabled_for_test')
        if name == 'search_web':
            args = SearchInput.model_validate(raw)
            self.reserve(mid, 'model_calls_used', 60, 'model_started')
            self.reserve(mid, 'network_requests_used', 200, 'network_started')
            result, usage = await self.call(mid, self.provider.search(args.query, args.k, self.guard(mid)['domains']))
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
                context = {'scope_approved':scope_approved, 'mission':{k:d[k] for k in ['subject','domains','created_at']},
                           'actions_remaining':d['action_budget']-d['actions_used'],
                           'saved_findings':[{'title':f['title'], 'finding_id':f['finding_id']} for f in d['findings']],
                           'recent_results':history[-4:]}
                name, raw, usage = await self.call(mid, self.provider.decide(context))
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
                    if raw:
                        raise ToolFailure('invalid_finish')
                    self.store.finish(mid, 'completed')
                    return
                self.reserve(mid, 'actions_used', d['action_budget'], 'action_reserved')
                d = self.guard(mid)
                d['current_action'] = name
                # Only schema-valid, bounded parameters enter the journal.
                schema = {'search_web':SearchInput, 'read_page':ReadInput, 'save_finding':SaveInput}.get(name)
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
                    if code.startswith('anthropic_http_') or code in {'web_search_unavailable', 'execution_error'}:
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
