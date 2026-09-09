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


@pytest.mark.parametrize('status',['stopped','budget_exhausted','deadline_reached'])
def test_recent_partial_with_finding_is_reused_for_free(tmp_path, status):
    path = tmp_path/'db'; mid = seed(path, status)
    store = Store(str(path))
    try:
        data = store.get(mid)
        data['findings'] = [{'finding_id':'one','title':'Constat conservé',
                             'summary':'Un fait étayé reste disponible.',
                             'developer_impact':'À consulter.', 'evidence':[],
                             'change':'new'}]
        store.save(data,'fixture_finding',{})
    finally:
        store.db.close()
    with TestClient(create_app(db_path=str(path),access_token=TOKEN,
                               provider=NeverCalled())) as client:
        response = client.post('/api/missions',headers=AUTH,json=REQUEST)
        assert response.status_code == 200
        assert response.json()['id'] == mid
        assert response.json()['reuse']['reason'] == 'recent_partial'
        assert not client.app.state.engine.active()


def test_completing_partial_reuses_recent_pages_and_selected_domains(tmp_path):
    path = tmp_path/'db'
    store = Store(str(path))
    request = MissionInput(subject='Veille automatique', auto_sources=True,
                           action_budget=20, duration_minutes=10)
    try:
        old = store.create(request)
        data = store.get(old)
        page = {'source_id':'source','url':'https://example.com/news',
                'title':'Annonce','text':'Un fait documenté.', 'published_at':None,
                'retrieved_at':'2026-09-09T10:00:00+00:00','status':'ok'}
        data.update(status='budget_exhausted', ended_epoch=time.time(),
                    ended_at='2026-09-09T10:01:00+00:00',
                    domains=['example.com'], selected_sources=[{
                        'domain':'example.com','url':page['url'],'reason':'Source primaire'}],
                    source_candidates=[{'domain':'example.com','url':page['url']}],
                    discovery_attempted=True, pages={'source':page},
                    sources=[{key:value for key,value in page.items() if key!='text'}])
        store.save(data,'finished',{'status':'budget_exhausted'})
        fresh = store.create(request.model_copy(update={'force_refresh':True}))
        resumed = store.get(fresh)
        assert resumed['domains'] == ['example.com']
        assert resumed['pages']['source']['text'] == 'Un fait documenté.'
        assert resumed['selected_sources'][0]['domain'] == 'example.com'
        assert any(event['kind']=='partial_context_reused'
                   for event in store.events(fresh))
    finally:
        store.db.close()

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
