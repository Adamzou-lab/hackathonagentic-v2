"""Streaming du palier 3. Aucun appel reseau : fournisseur et transport simules."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.stream import Broker, frame
from app.agent.provider import AnthropicProvider

TOKEN = 'x' * 40
MISSION = {'subject':'sujet de test', 'domains':['www.anthropic.com'],
           'action_budget':3, 'duration_minutes':1}


class SlowProvider:
    """Emet des fragments provisoires, puis rend une action complete."""
    def __init__(self):
        self.broker = None
        self.mission_id = None

    def bind(self, mid):
        self.mission_id = mid

    def emit(self, phase, **fields):
        if self.broker and self.mission_id:
            self.broker.publish(self.mission_id,
                                dict(mission_id=self.mission_id, phase=phase, **fields))

    async def decide(self, context):
        self.emit('tool_input_started', action='save_finding', block=0)
        for part in ('{"finding":', ' {"title"', ': "x"}}'):
            self.emit('tool_input', block=0, partial_json=part)
            await asyncio.sleep(0.05)
        self.emit('tool_input_complete', block=0, action='finish')
        await asyncio.sleep(0.05)
        return 'finish', {}, {'input_tokens': 1, 'output_tokens': 1}

    async def search(self, query, k, domains):
        return [], {}

    async def close(self):
        pass


def build(tmp_path):
    provider = SlowProvider()
    app = create_app(db_path=str(tmp_path/'t.db'), access_token=TOKEN, provider=provider)
    return app, provider


def read_events(raw):
    """Decoupe un corps SSE en (id, event, data)."""
    out = []
    for block in raw.split('\n\n'):
        if not block.strip() or block.startswith(':'):
            continue
        eid = kind = None
        data = ''
        for line in block.splitlines():
            if line.startswith('id: '): eid = line[4:]
            elif line.startswith('event: '): kind = line[7:]
            elif line.startswith('data: '): data = line[6:]
        out.append((eid, kind, json.loads(data) if data else None))
    return out


def test_refus_sans_authentification(tmp_path):
    app, _ = build(tmp_path)
    with TestClient(app) as client:
        mid = client.post('/api/missions', json=MISSION,
                          headers={'Authorization': f'Bearer {TOKEN}'}).json()['id']
        assert client.get(f'/api/missions/{mid}/stream').status_code == 401
        assert client.get(f'/api/missions/{mid}/stream',
                          headers={'Authorization': 'Bearer ' + 'y'*40}).status_code == 401


def test_mission_inconnue(tmp_path):
    app, _ = build(tmp_path)
    with TestClient(app) as client:
        r = client.get('/api/missions/inexistante/stream',
                       headers={'Authorization': f'Bearer {TOKEN}'})
        assert r.status_code == 404


def test_flux_progressif_et_ordre(tmp_path):
    """Le flux doit livrer des fragments AVANT la fin, puis se clore proprement."""
    app, provider = build(tmp_path)
    with TestClient(app) as client:
        provider.broker = app.state.broker
        mid = client.post('/api/missions', json=MISSION,
                          headers={'Authorization': f'Bearer {TOKEN}'}).json()['id']
        with client.stream('GET', f'/api/missions/{mid}/stream',
                           headers={'Authorization': f'Bearer {TOKEN}'}) as response:
            assert response.status_code == 200
            assert response.headers['content-type'].startswith('text/event-stream')
            body = ''.join(response.iter_text())
    events = read_events(body)
    kinds = [k for _, k, _ in events]
    assert 'draft' in kinds, 'aucun fragment provisoire recu'
    assert kinds[-1] == 'end', 'le flux ne se termine pas par end'
    # Le journal est ordonne et strictement croissant.
    seqs = [d['seq'] for _, k, d in events if k == 'journal']
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
    # Un fragment provisoire ne porte jamais d'identifiant rejouable.
    assert all(eid is None for eid, k, _ in events if k == 'draft')
    # Le dernier evenement annonce un etat terminal.
    assert events[-1][2]['status'] in {'completed','stopped','failed',
                                       'budget_exhausted','deadline_reached'}


def test_reprise_sans_doublon(tmp_path):
    """Last-Event-ID reprend apres le seq fourni, sans rejouer ni relancer."""
    app, provider = build(tmp_path)
    with TestClient(app) as client:
        provider.broker = app.state.broker
        head = {'Authorization': f'Bearer {TOKEN}'}
        mid = client.post('/api/missions', json=MISSION, headers=head).json()['id']
        with client.stream('GET', f'/api/missions/{mid}/stream', headers=head) as r:
            complet = ''.join(r.iter_text())
        seqs = [d['seq'] for _, k, d in read_events(complet) if k == 'journal']
        coupure = seqs[len(seqs)//2]
        with client.stream('GET', f'/api/missions/{mid}/stream',
                           headers={**head, 'Last-Event-ID': str(coupure)}) as r:
            reprise = ''.join(r.iter_text())
        repris = [d['seq'] for _, k, d in read_events(reprise) if k == 'journal']
        assert all(s > coupure for s in repris), 'des evenements ont ete rejoues'
        assert repris == sorted(repris)


def test_deconnexion_ne_relance_pas(tmp_path):
    """Se connecter puis partir ne doit creer aucune seconde mission."""
    app, provider = build(tmp_path)
    with TestClient(app) as client:
        provider.broker = app.state.broker
        head = {'Authorization': f'Bearer {TOKEN}'}
        mid = client.post('/api/missions', json=MISSION, headers=head).json()['id']
        for _ in range(3):
            with client.stream('GET', f'/api/missions/{mid}/stream', headers=head) as r:
                next(r.iter_text(), None)
        events = client.get(f'/api/missions/{mid}/events', headers=head).json()
        assert sum(1 for e in events if e['kind'] == 'created') == 1
        assert sum(1 for e in events if e['kind'] == 'started') <= 1


def test_broker_borne_ne_grossit_pas():
    """Un client lent perd des fragments plutot que la memoire du serveur."""
    async def scenario():
        broker = Broker()
        queue = broker.subscribe('m')
        for i in range(1000):
            broker.publish('m', {'i': i})
        assert queue.qsize() <= 256
        broker.unsubscribe('m', queue)
        assert 'm' not in broker.subscribers
    asyncio.run(scenario())


def test_assemblage_du_flux_fournisseur():
    """Le JSON d'un outil n'est expose qu'une fois complet."""
    provider = AnthropicProvider('cle-non-utilisee', 'modele')
    blocks, buffers = {}, {}
    provider.consume({'type':'content_block_start', 'index':0,
                      'content_block':{'type':'tool_use','name':'search_web','input':{}}}, blocks, buffers)
    for part in ('{"query"', ': "abc"', ', "k": 3}'):
        provider.consume({'type':'content_block_delta', 'index':0,
                          'delta':{'type':'input_json_delta','partial_json':part}}, blocks, buffers)
    assert blocks[0].get('input') == {}, 'arguments exposes avant la fin du bloc'
    provider.consume({'type':'content_block_stop', 'index':0}, blocks, buffers)
    assert blocks[0]['input'] == {'query':'abc', 'k':3}


def test_json_tronque_est_neutralise():
    """Un JSON coupe ne doit jamais devenir un appel d'outil executable."""
    provider = AnthropicProvider('cle', 'modele')
    blocks, buffers = {}, {}
    provider.consume({'type':'content_block_start', 'index':0,
                      'content_block':{'type':'tool_use','name':'read_page','input':{}}}, blocks, buffers)
    provider.consume({'type':'content_block_delta', 'index':0,
                      'delta':{'type':'input_json_delta','partial_json':'{"url": "https://a'}}, blocks, buffers)
    provider.consume({'type':'content_block_stop', 'index':0}, blocks, buffers)
    assert blocks[0]['input'] == {}
    assert blocks[0]['truncated'] is True


def test_raisonnement_interne_jamais_diffuse():
    """Les blocs de reflexion ne doivent produire aucun fragment."""
    provider = AnthropicProvider('cle', 'modele')
    emis = []
    provider.broker = type('B', (), {'publish': lambda self, m, p: emis.append(p)})()
    provider.mission_id = 'm'
    blocks, buffers = {}, {}
    provider.consume({'type':'content_block_delta', 'index':0,
                      'delta':{'type':'thinking_delta','thinking':'secret interne'}}, blocks, buffers)
    provider.consume({'type':'content_block_delta', 'index':0,
                      'delta':{'type':'signature_delta','signature':'abc'}}, blocks, buffers)
    assert emis == []
