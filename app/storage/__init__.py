"""SQLite snapshots and append-only events committed in the same transaction."""
import json
import sqlite3
import time
import uuid
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

TERMINAL = {'refused', 'stopped', 'completed', 'budget_exhausted', 'deadline_reached', 'failed'}


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (mission_id TEXT, seq INTEGER, at TEXT, kind TEXT, data TEXT, PRIMARY KEY(mission_id,seq))')
        self.db.commit()

    def get(self, mid):
        row = self.db.execute('SELECT data FROM missions WHERE id=?', (mid,)).fetchone()
        if row is None:
            raise KeyError(mid)
        return json.loads(row[0])

    @staticmethod
    def request_identity(data):
        # Comparaison déterministe : aucune classification ni requête au modèle.
        subject = ' '.join(unicodedata.normalize('NFC', data['subject']).casefold().split())
        return (subject, tuple(sorted(set(data['domains']))),
                data['action_budget'], data['duration_minutes'])

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
            if data.get('had_errors') or self.request_identity(data) != wanted:
                continue
            return data['id']
        return None

    def create(self, request):
        mid = uuid.uuid4().hex
        data = dict(id=mid, **request.model_dump(), status='pending', created_at=now(),
                    ended_at=None, started_epoch=time.time(), ended_epoch=None,
                    actions_used=0, model_calls_used=0, network_requests_used=0,
                    last_request_cost=None, total_estimated_cost_usd=0,
                    current_action=None, error=None, sources=[], findings=[], pages={},
                    keys={}, attempts={}, had_errors=False)
        self.save(data, 'created', {'request': request.model_dump()})
        return mid

    def save(self, data, kind, event):
        # Called synchronously on the event loop: no await between read and commit.
        with self.db:
            seq = self.db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE mission_id=?', (data['id'],)).fetchone()[0]
            self.db.execute('INSERT INTO missions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                            (data['id'], json.dumps(data, ensure_ascii=False)))
            self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                            (data['id'], seq, now(), kind, json.dumps(event, ensure_ascii=False)))

    def events(self, mid):
        return [dict(seq=r[0], at=r[1], kind=r[2], data=json.loads(r[3])) for r in
                self.db.execute('SELECT seq,at,kind,data FROM events WHERE mission_id=? ORDER BY seq', (mid,))]

    def finish(self, mid, status, error=None):
        data = self.get(mid)
        if data['status'] in TERMINAL:
            return
        data.update(status=status, error=error, ended_at=now(), ended_epoch=time.time(), current_action=None)
        self.save(data, 'finished', {'status': status, 'error': error, 'actions_used': data['actions_used']})

    def recover(self):
        for (mid,) in self.db.execute('SELECT id FROM missions').fetchall():
            data = self.get(mid)
            if data['status'] not in TERMINAL:
                self.finish(mid, 'failed', 'Processus interrompu ; résultat de toute action inachevée inconnu.')

    def snapshot(self, mid):
        data = self.get(mid)
        duration = data['duration_minutes'] * 60
        elapsed = max(0, int((data['ended_epoch'] or time.time()) - data['started_epoch']))
        public = {k: v for k, v in data.items() if k not in
                  {'pages', 'keys', 'attempts', 'started_epoch', 'ended_epoch', 'had_errors'}}
        # Compatibilité avec les missions créées avant le palier 5.
        public.setdefault('last_request_cost', None)
        public.setdefault('total_estimated_cost_usd', 0)
        public.update(duration_seconds=duration, elapsed_seconds=elapsed,
                      remaining_seconds=max(0, duration-elapsed),
                      actions_remaining=max(0, data['action_budget']-data['actions_used']), events=self.events(mid))
        text = '\n\n'.join(f"{f['title']}\n{f['summary']}\nIntérêt pratique : {f['developer_impact']}" for f in data['findings'])
        public['summary'] = {'partial': data['status'] != 'completed' or data['had_errors'],
                             'text': data.get('refusal_reason') or text or 'Aucun résultat exploitable pour le moment.'}
        return public
