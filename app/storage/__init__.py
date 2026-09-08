"""SQLite snapshots and append-only events committed in the same transaction."""
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from app.storage.usage import usage_summary
from app.storage.watches import WatchStore, watch_identity
from app.storage.incidents import GuardedConnection, IncidentLog, StorageUnavailable, mission_context, json_guard

TERMINAL = {'refused', 'stopped', 'completed', 'budget_exhausted', 'deadline_reached', 'failed'}


def now():
    return datetime.now(timezone.utc).isoformat()


class Store(WatchStore):
    def __init__(self, path, incident_path=None):
        db_path = Path(path).absolute()
        incident_path = incident_path or db_path.with_name(db_path.name + '.incidents.jsonl')
        self.db = GuardedConnection(db_path, IncidentLog(incident_path))
        try:
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS events (mission_id TEXT, seq INTEGER, at TEXT, kind TEXT, data TEXT, PRIMARY KEY(mission_id,seq))')
            self.db.execute('CREATE TABLE IF NOT EXISTS api_control (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, changed_at TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS api_control_events (at TEXT NOT NULL, enabled INTEGER NOT NULL)')
            self.db.execute('INSERT OR IGNORE INTO api_control VALUES (1,1,?)', (now(),))
            self.db.commit()
            self.init_watches()
        except BaseException:
            self.db.close()
            raise

    @property
    def unavailable(self):
        return self.db.unavailable

    def check_available(self):
        self.db.check_available()

    def api_control(self):
        row = self.db.execute('SELECT enabled, changed_at FROM api_control WHERE id=1').fetchone()
        if row is None or row[0] not in (0, 1):
            self.db._fail('storage_data_invalid', 'api_control')
        return {'api_enabled': bool(row[0]), 'api_changed_at': row[1]}

    def set_api_enabled(self, enabled):
        if self.api_control()['api_enabled'] != enabled:
            at = now()
            with self.db:
                self.db.execute('UPDATE api_control SET enabled=?, changed_at=? WHERE id=1', (int(enabled), at))
                self.db.execute('INSERT INTO api_control_events VALUES (?,?)', (at, int(enabled)))
        return self.api_control()

    def incidents(self, limit=100):
        return self.db.incident_log.read_recent(limit)

    @json_guard
    def init_watches(self):
        return super().init_watches()

    @json_guard
    def exact_watch(self, request):
        return super().exact_watch(request)

    @json_guard
    def watch_runs(self, wid):
        return super().watch_runs(wid)

    @mission_context
    @json_guard
    def get(self, mid):
        row = self.db.execute('SELECT data FROM missions WHERE id=?', (mid,)).fetchone()
        if row is None:
            raise KeyError(mid)
        result = json.loads(row[0])
        if not isinstance(result, dict):
            self.db._fail('storage_data_invalid', 'decode')
        return result

    @staticmethod
    def request_identity(data):
        # Comparaison déterministe : aucune classification ni requête au modèle.
        return (*watch_identity(data), data['action_budget'], data['duration_minutes'])

    @json_guard
    def reusable(self, request, max_age_seconds=86400):
        wanted = self.request_identity(request.model_dump())
        cutoff = time.time() - max_age_seconds
        rows = self.db.execute(
            "SELECT data FROM missions WHERE "
            "json_extract(data, '$.status') IN ('pending', 'running') OR "
            "(json_extract(data, '$.status') = 'completed' AND "
            "json_extract(data, '$.ended_epoch') >= ?) "
            "ORDER BY json_extract(data, '$.started_epoch') DESC", (cutoff,))
        for (encoded,) in rows:
            data = json.loads(encoded)
            if request.watch_id and self.watch_id_for(data['id']) != request.watch_id:
                continue
            if request.force_refresh and data['status'] == 'completed':
                continue
            if data.get('had_errors') or self.request_identity(data) != wanted:
                continue
            return data['id']
        return None

    def create(self, request, watch_id=None):
        mid = uuid.uuid4().hex
        wid = watch_id or request.watch_id or self.exact_watch(request)
        previous = self.prior_context(wid, request.domains, request.auto_sources) if wid else {}
        wid = wid or mid
        inputs = request.model_dump(exclude={'watch_id','force_refresh','allow_new'})
        data = dict(id=mid, watch_id=wid, **inputs, **previous, status='pending', created_at=now(),
                    ended_at=None, started_epoch=time.time(), ended_epoch=None,
                    actions_used=0, model_calls_used=0, network_requests_used=0,
                    token_budget=16000 if request.action_budget <= 10 else (24000 if request.action_budget <= 20 else 40000),
                    current_action=None, current_operation=None, error=None, sources=[], findings=[], pages={},
                    keys={}, attempts={}, had_errors=False)
        self.save(data, 'created', {'request': request.model_dump()})
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO watches VALUES (?,?,?)', (wid,request.subject,data['created_at']))
            self.db.execute('INSERT INTO watch_runs VALUES (?,?)', (mid,wid))
        if previous:
            self.save(data, 'enrichment_prepared', {'base_mission_id':previous['base_mission_id'],
                'known_findings':previous['known_findings'], 'known_findings_count':len(previous['known_findings']),
                'known_findings_truncated':previous['known_findings_truncated'], 'update_since':previous['update_since']})
        return mid

    @mission_context
    def save(self, data, kind, event):
        # Called synchronously on the event loop: no await between read and commit.
        with self.db:
            self._persist(data, kind, event)

    def _persist(self, data, kind, event):
        at = now()
        data['last_seen_at'] = at
        seq = self.db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE mission_id=?', (data['id'],)).fetchone()[0]
        self.db.execute('INSERT INTO missions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        (data['id'], json.dumps(data, ensure_ascii=False)))
        self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                        (data['id'], seq, at, kind, json.dumps(event, ensure_ascii=False)))

    @mission_context
    @json_guard
    def events(self, mid):
        return [dict(seq=r[0], at=r[1], kind=r[2], data=json.loads(r[3])) for r in
                self.db.execute('SELECT seq,at,kind,data FROM events WHERE mission_id=? ORDER BY seq', (mid,))]

    @mission_context
    def finish(self, mid, status, error=None):
        data = self.get(mid)
        already_terminal = data['status'] in TERMINAL
        with self.db:
            operation = data.get('current_operation')
            if operation:
                data['current_operation'] = None
                data['had_errors'] = True
                self._persist(data, 'operation_finished', {
                    'operation_id': operation.get('id'), 'dependency': operation.get('dependency'),
                    'operation': operation.get('operation'), 'outcome': 'unknown',
                    'code': 'interrupted',
                })
            if data.get('current_action') is not None:
                action = data['current_action']
                data['current_action'] = None
                data['had_errors'] = True
                self._persist(data, 'action_finished', {
                    'tool': action, 'action_number': data['actions_used'],
                    'result': {'status': 'unknown', 'error': 'interrupted'},
                })
            if not already_terminal:
                data.update(status=status, error=error, ended_at=now(), ended_epoch=time.time())
                self._persist(data, 'finished', {'status': status, 'error': error, 'actions_used': data['actions_used']})

    def recover(self):
        for (mid,) in self.db.execute('SELECT id FROM missions').fetchall():
            data = self.get(mid)
            if data['status'] not in TERMINAL:
                last_event = self.db.execute('SELECT at FROM events WHERE mission_id=? ORDER BY seq DESC LIMIT 1', (mid,)).fetchone()
                # Une panne pendant la récupération ne transforme pas sa propre
                # trace de détection en dernière activité du moteur interrompu.
                data['recovery_last_seen_at'] = data.get('recovery_last_seen_at') or (
                    last_event[0] if last_event else data.get('last_seen_at') or data.get('created_at'))
                self.save(data, 'recovery_detected', {
                    'last_seen_at': data['recovery_last_seen_at'],
                    'interrupted_at': None, 'reaction': 'stop',
                })
                self.finish(mid, 'failed', 'process_interrupted')

    def snapshot(self, mid):
        data = self.get(mid)
        duration = data['duration_minutes'] * 60
        elapsed = max(0, int((data['ended_epoch'] or time.time()) - data['started_epoch']))
        public = {k: v for k, v in data.items() if k not in
                  {'pages', 'keys', 'attempts', 'started_epoch', 'ended_epoch', 'had_errors'}}
        public['watch_id'] = self.watch_id_for(mid)
        public['new_findings_count'] = sum(f.get('change','new') == 'new' for f in data['findings'])
        public['updated_findings_count'] = sum(f.get('change') == 'update' for f in data['findings'])
        public.update(duration_seconds=duration, elapsed_seconds=elapsed,
                      remaining_seconds=max(0, duration-elapsed),
                      actions_remaining=max(0, data['action_budget']-data['actions_used']), events=self.events(mid))
        public['usage'] = usage_summary(data, public['events'], elapsed)
        text = '\n\n'.join(f"{f['title']}\n{f['summary']}\nIntérêt pratique : {f['developer_impact']}" for f in data['findings'])
        empty = 'Aucun constat validé pour le moment.'
        if data['status'] == 'budget_exhausted':
            empty = 'Budget épuisé avant la sauvegarde d’un constat validé. Consultez le journal pour voir les lectures et les erreurs rencontrées.'
            if any(e['kind'] == 'token_budget_exhausted' for e in public['events']):
                empty = 'Seuil de tokens atteint : aucun nouvel appel IA lancé. Aucun constat validé avant cet arrêt.'
        elif data['status'] == 'deadline_reached':
            empty = 'Durée limite atteinte avant la sauvegarde d’un constat validé.'
        elif data['status'] == 'completed':
            empty = 'Recherche terminée sans constat étayé à conserver sur les sources consultées.'
        elif data['status'] in {'failed','stopped'}:
            empty = 'Mission interrompue avant la sauvegarde d’un constat validé. Consultez le journal.'
        public['summary'] = {'partial': data['status'] != 'completed' or data['had_errors'],
                             'text': data.get('refusal_reason') or text or empty}
        return public
