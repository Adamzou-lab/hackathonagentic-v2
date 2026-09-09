"""Fiches de veille stables ; les exécutions et leurs preuves restent immuables."""
import hashlib
import json
import re
import time
import unicodedata
from difflib import SequenceMatcher


def normalize_subject(text):
    return ' '.join(unicodedata.normalize('NFC', text).casefold().split())


def watch_identity(data):
    auto = data.get('auto_sources', False)
    return (normalize_subject(data['subject']), auto,
            () if auto else tuple(sorted(set(data['domains']))))


def finding_key(finding, links):
    # Une reformulation de titre seule ne crée pas une nouvelle information.
    value = (normalize_subject(finding['summary']), finding.get('event_date'),
             sorted((e.get('url', ''), normalize_subject(e.get('quote', ''))) for e in links))
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


class WatchStore:
    def init_watches(self):
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS watches (id TEXT PRIMARY KEY, subject TEXT NOT NULL, created_at TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS watch_runs (mission_id TEXT PRIMARY KEY, watch_id TEXT NOT NULL)')
            self.db.execute('CREATE INDEX IF NOT EXISTS watch_runs_watch ON watch_runs(watch_id)')
            # Migration idempotente : n'altère ni les snapshots ni les journaux passés.
            rows = self.db.execute('SELECT m.data FROM missions m LEFT JOIN watch_runs r ON r.mission_id=m.id '
                                   "WHERE r.mission_id IS NULL ORDER BY json_extract(m.data, '$.started_epoch'),m.id").fetchall()
            for (encoded,) in rows:
                data = json.loads(encoded)
                wid = self.exact_watch(data) or data['id']
                self.db.execute('INSERT OR IGNORE INTO watches VALUES (?,?,?)', (wid,data['subject'],data['created_at']))
                self.db.execute('INSERT INTO watch_runs VALUES (?,?)', (data['id'],wid))

    def watch_id_for(self, mid):
        row = self.db.execute('SELECT watch_id FROM watch_runs WHERE mission_id=?', (mid,)).fetchone()
        if not row:
            raise KeyError(mid)
        return row[0]

    def exact_watch(self, request):
        data = request.model_dump() if hasattr(request,'model_dump') else request
        wanted = watch_identity(data)
        rows = self.db.execute('SELECT m.data,r.watch_id FROM missions m JOIN watch_runs r ON r.mission_id=m.id '
                               'JOIN watches w ON w.id=r.watch_id ORDER BY w.created_at,w.id')
        for encoded, wid in rows:
            if watch_identity(json.loads(encoded)) == wanted:
                return wid
        return None

    def watch_runs(self, wid):
        if not self.db.execute('SELECT 1 FROM watches WHERE id=?',(wid,)).fetchone():
            raise KeyError(wid)
        return [json.loads(r[0]) for r in self.db.execute(
            'SELECT m.data FROM missions m JOIN watch_runs r ON m.id=r.mission_id WHERE r.watch_id=? '
            "ORDER BY json_extract(m.data, '$.started_epoch'),m.id", (wid,))]

    def watch(self, wid):
        runs = self.watch_runs(wid)
        meta = self.db.execute('SELECT subject,created_at FROM watches WHERE id=?',(wid,)).fetchone()
        entries, seen, summary_runs = {}, set(), []
        for run in runs:
            sources = {s.get('source_id'):s for s in run['sources'] if s.get('status') == 'ok'}
            added = updated = 0
            for finding in run['findings']:
                links = [{'url':sources[e['source_id']]['url'], 'title':sources[e['source_id']].get('title',''),
                          'quote':e['quote']} for e in finding['evidence'] if e['source_id'] in sources]
                key = finding_key(finding, links)
                related = finding.get('related_finding_id')
                explicit_update = finding.get('change') == 'update' and related in entries
                if finding.get('change') == 'duplicate' or (key in seen and not explicit_update):
                    continue
                change = 'updated' if finding.get('change') == 'update' and related in entries else 'new'
                entry = {**finding, 'entry_id':run['id']+':'+finding['finding_id'],
                         'mission_id':run['id'], 'source_links':links, 'change':change,
                         'added_at':run['created_at']}
                if change == 'updated':
                    # Ancienne version accessible via sa mission, jamais écrasée en base.
                    entry['previous_versions'] = entries[related].get('previous_versions',[]) + [related]
                    del entries[related]
                    updated += 1
                else:
                    added += 1
                entries[entry['entry_id']] = entry
                seen.add(key)
            summary_runs.append({k:run.get(k) for k in ('id','subject','created_at','ended_at','status','actions_used','action_budget','duration_minutes')} |
                                {'partial':run['status'] != 'completed' or run.get('had_errors',False), 'findings_count':len(run['findings']), 'new_findings_count':added, 'updated_findings_count':updated})
        latest = runs[-1] if runs else {}
        return {'id':wid, 'subject':meta[0], 'created_at':meta[1],
                'updated_at':latest.get('ended_at') or latest.get('created_at',meta[1]),
                'latest_mission_id':latest.get('id'), 'status':latest.get('status','pending'),
                'domains':latest.get('domains',[]), 'auto_sources':latest.get('auto_sources',False),
                'action_budget':latest.get('action_budget',20), 'duration_minutes':latest.get('duration_minutes',10),
                'findings_count':len(entries),'run_count':len(runs),
                'findings':list(entries.values()),'runs':list(reversed(summary_runs))}

    def list_watches(self, query='', limit=50, offset=0):
        wanted = normalize_subject(query)
        rows = self.db.execute('SELECT id,subject FROM watches ORDER BY created_at DESC,id').fetchall()
        matches = [wid for wid,subject in rows if wanted in normalize_subject(subject)]
        items = []
        for wid in matches[offset:offset+limit]:
            watch = self.watch(wid)
            items.append({k:v for k,v in watch.items() if k not in {'findings','runs'}})
        return {'watches':items,'total':len(matches)}

    def similar_watches(self, request):
        subject = normalize_subject(request.subject)
        words = set(re.findall(r'\w+',subject))
        candidates = []
        for wid,title in self.db.execute('SELECT id,subject FROM watches ORDER BY created_at,id'):
            other = normalize_subject(title)
            other_words = set(re.findall(r'\w+',other))
            overlap = len(words & other_words) / max(1,len(words | other_words))
            score = max(SequenceMatcher(None,subject,other).ratio(),overlap)
            if score >= 0.64:
                watch = self.watch(wid)
                candidates.append(({k:v for k,v in watch.items() if k not in {'findings','runs'}},score))
        candidates.sort(key=lambda x:(-x[1],x[0]['created_at']))
        return [c for c,_ in candidates[:3]]

    def prior_context(self, wid, allowed_domains, auto_sources=False):
        watch = self.watch(wid)
        findings = watch['findings']
        compact, total = [], 0
        for f in reversed(findings):
            from urllib.parse import urlsplit
            urls = [s['url'] for s in f['source_links']]
            # Une nouvelle limite manuelle exclut aussi le contexte issu d'autres sites.
            if not auto_sources and any(urlsplit(u).hostname not in allowed_domains for u in urls):
                continue
            item = {k:f.get(k) for k in ('entry_id','title','summary','event_date')}
            item['summary'] = (item['summary'] or '')[:400]
            item['urls'] = urls[:5]
            size = len(json.dumps(item,ensure_ascii=False))
            if len(compact) >= 20 or total+size > 12000:
                break
            compact.append(item);total += size
        completed = next((r for r in watch['runs'] if r['status']=='completed' and not r['partial']),None)
        latest = self.watch_runs(wid)[-1]
        ended_epoch = latest.get('ended_epoch') or 0
        reusable_partial = (latest.get('status') in {'budget_exhausted','deadline_reached','stopped'}
                            and time.time() - ended_epoch <= 21600)
        cached_pages = latest.get('pages', {}) if reusable_partial else {}
        resume = {}
        if cached_pages:
            resume['cached_pages'] = dict(list(cached_pages.items())[-2:])
            resume['domains'] = latest.get('domains', [])
            resume['selected_sources'] = latest.get('selected_sources', [])
            resume['source_candidates'] = latest.get('source_candidates', [])
            resume['discovery_attempted'] = latest.get('discovery_attempted', False)
            resume['sources'] = [source for source in latest.get('sources', [])
                                 if source.get('source_id') in resume['cached_pages']]
        return {'known_findings':compact,'known_findings_truncated':len(compact)<len(findings),
                'update_since':completed['ended_at'] if completed else None,
                'base_mission_id':watch['latest_mission_id'], **resume}
