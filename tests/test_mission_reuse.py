"""Réutilisation persistante sans nouveau lancement ni appel au modèle."""
import time
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.schemas import MissionInput
from app.storage import Store

TOKEN='reuse-test-'+'x'*32
AUTH={'Authorization':'Bearer '+TOKEN}
REQUEST={'subject':'Veille PostgreSQL', 'domains':['example.com','postgresql.org'], 'action_budget':3, 'duration_minutes':1}

class NeverCalled:
    async def decide(self,context):
        pytest.fail('Réutiliser une mission ne doit pas appeler le modèle')

def seed(path, status='completed', age=0, had_errors=False):
    store=Store(str(path))
    mid=store.create(MissionInput(**REQUEST))
    data=store.get(mid)
    data.update(status=status,had_errors=had_errors, ended_epoch=time.time()-age,
                ended_at='2026-09-08T10:00:00+00:00')
    store.save(data,'finished',{'status':status})
    store.db.close()
    return mid

def test_completed_survives_restart_and_is_reused_without_events(tmp_path):
    path=tmp_path/'db';mid=seed(path)
    with TestClient(create_app(db_path=str(path),access_token=TOKEN,provider=NeverCalled())) as client:
        before=client.get('/api/missions/'+mid,headers=AUTH).json()
        for request in [REQUEST, {**REQUEST,'subject':'  veille   POSTGRESQL  ','domains':['postgresql.org','example.com']}]:
            response=client.post('/api/missions',headers=AUTH,json=request)
            assert response.status_code==200
            assert response.json()['id']==mid
            assert response.json()['reuse']['reason']=='recent_completed'
        after=client.get('/api/missions/'+mid,headers=AUTH).json()
        assert before==after
        assert not client.app.state.engine.active()
        assert client.app.state.store.db.execute('SELECT COUNT(*) FROM missions').fetchone()[0]==1
        assert client.post('/api/missions',json=REQUEST).status_code==401

@pytest.mark.parametrize('status,age,errors',[
    ('completed',86401,False),('failed',0,False),('refused',0,False),
    ('stopped',0,False),('budget_exhausted',0,False),('deadline_reached',0,False),('completed',0,True)])
def test_unsuitable_missions_not_reused(tmp_path,status,age,errors):
    path=tmp_path/'db';seed(path,status,age,errors)
    store=Store(str(path))
    try: assert store.reusable(MissionInput(**REQUEST)) is None
    finally: store.db.close()

@pytest.mark.parametrize('change',[{'subject':'Veille Python'}, {'domains':['other.org']}, {'action_budget':4}, {'duration_minutes':2}])
def test_distinct_parameters_not_merged(tmp_path,change):
    path=tmp_path/'db';seed(path);store=Store(str(path))
    try: assert store.reusable(MissionInput(**{**REQUEST,**change})) is None
    finally: store.db.close()

def test_same_running_mission_reused_but_different_one_conflicts(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path/'db'),access_token=TOKEN,provider=NeverCalled())) as client:
        store=client.app.state.store
        mid=store.create(MissionInput(**REQUEST))
        # Pas de tâche réelle : simule un moteur occupé, aucun appel payant.
        client.app.state.engine.active=lambda: True
        response=client.post('/api/missions',headers=AUTH,json=REQUEST)
        assert response.status_code==200 and response.json()['id']==mid
        assert response.json()['reuse']['reason']=='already_running'
        assert client.post('/api/missions',headers=AUTH,json={**REQUEST,'subject':'Autre veille'}).status_code==409
