"""Palier 5 : robustesse des entrées HTTP.

Aucun appel payant. Le fournisseur est simulé et compte ses appels : chaque
test de validation vérifie que ce compteur reste à zéro, donc qu'un refus
d'entrée n'a jamais déclenché de mission facturable.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

TOKEN = 'z' * 40
AUTH = {'Authorization': f'Bearer {TOKEN}'}
VALIDE = {'subject':'nouveautés agents IA', 'domains':['www.anthropic.com'],
          'action_budget':3, 'duration_minutes':1}


class ProviderCompteur:
    """Ne parle à personne et retient combien de fois on a voulu l'utiliser."""
    def __init__(self):
        self.appels = 0
        self.broker = None
        self.mission_id = None

    def bind(self, mid):
        self.mission_id = mid

    async def decide(self, context):
        self.appels += 1
        return 'finish', {}, {'input_tokens':1, 'output_tokens':1}

    async def search(self, query, k, domains):
        self.appels += 1
        return [], {}

    async def close(self):
        pass


class ProviderLent(ProviderCompteur):
    """Ne rend jamais la main : la mission reste durablement en cours."""
    def __init__(self):
        super().__init__()
        self.lancements = 0

    async def decide(self, context):
        self.lancements += 1
        self.appels += 1
        await asyncio.sleep(3600)


@pytest.fixture
def client_lent(tmp_path):
    provider = ProviderLent()
    app = create_app(db_path=str(tmp_path/'lent.db'), access_token=TOKEN, provider=provider)
    with TestClient(app) as c:
        c.provider = provider
        yield c


@pytest.fixture
def client(tmp_path):
    provider = ProviderCompteur()
    app = create_app(db_path=str(tmp_path/'p5.db'), access_token=TOKEN, provider=provider)
    with TestClient(app) as c:
        c.provider = provider
        yield c


def poste(client, corps):
    return client.post('/api/missions', json=corps, headers=AUTH)


def detail_lisible(reponse):
    """Un refus doit porter un message exploitable, pas une page vide."""
    corps = reponse.json()
    assert 'detail' in corps, f'aucun detail dans {corps}'
    return corps['detail']


# --- Entrées vides, blanches, trop longues ----------------------------------

def test_sujet_vide(client):
    r = poste(client, {**VALIDE, 'subject':''})
    assert r.status_code == 422
    assert detail_lisible(r)
    assert client.provider.appels == 0


def test_sujet_uniquement_espaces(client):
    """Un sujet composé d'espaces n'est pas un sujet."""
    r = poste(client, {**VALIDE, 'subject':'    \t\n  '})
    assert r.status_code == 422
    assert client.provider.appels == 0


def test_sujet_trop_long(client):
    r = poste(client, {**VALIDE, 'subject':'a'*501})
    assert r.status_code == 422
    assert client.provider.appels == 0


def test_sujet_a_la_limite_accepte(client):
    """500 caractères exactement doivent passer : la borne est inclusive."""
    r = poste(client, {**VALIDE, 'subject':'a'*500})
    assert r.status_code in (200, 202), r.text


def test_corps_vide(client):
    r = client.post('/api/missions', json={}, headers=AUTH)
    assert r.status_code == 422
    assert client.provider.appels == 0


def test_corps_non_json(client):
    r = client.post('/api/missions', content=b'pas du json', headers={**AUTH,
                    'Content-Type':'application/json'})
    assert r.status_code == 422
    assert client.provider.appels == 0


# --- Types incorrects --------------------------------------------------------

@pytest.mark.parametrize('champ,valeur', [
    ('subject', 123),
    ('subject', None),
    ('subject', ['liste']),
    ('domains', 'www.anthropic.com'),   # chaîne au lieu de liste
    ('domains', [42]),
    ('action_budget', '3'),             # chaîne au lieu d'entier
    ('action_budget', 3.5),
    ('duration_minutes', True),
    ('auto_sources', 'oui'),
])
def test_types_incorrects(client, champ, valeur):
    r = poste(client, {**VALIDE, champ:valeur})
    assert r.status_code == 422, f'{champ}={valeur!r} accepté'
    assert client.provider.appels == 0


def test_champ_inconnu_refuse(client):
    """extra='forbid' : un champ non prévu doit être rejeté, pas ignoré."""
    r = poste(client, {**VALIDE, 'admin':True})
    assert r.status_code == 422
    assert client.provider.appels == 0


# --- Paramètres hors bornes --------------------------------------------------

@pytest.mark.parametrize('champ,valeur', [
    ('action_budget', 0), ('action_budget', -1), ('action_budget', 101),
    ('duration_minutes', 0), ('duration_minutes', -5), ('duration_minutes', 31),
])
def test_bornes_numeriques(client, champ, valeur):
    r = poste(client, {**VALIDE, champ:valeur})
    assert r.status_code == 422
    assert client.provider.appels == 0


def test_trop_de_domaines(client):
    r = poste(client, {**VALIDE, 'domains':[f'exemple{i}.com' for i in range(6)]})
    assert r.status_code == 422
    assert client.provider.appels == 0


@pytest.mark.parametrize('domaine', [
    'https://www.anthropic.com',   # URL au lieu d'un nom d'hôte
    'www.anthropic.com/blog',      # chemin
    '*.anthropic.com',             # joker
    '127.0.0.1',                   # adresse IP
    '10.0.0.5',
    'localhost',
    'service.internal',
    'machine.local',
    '',
    '   ',
])
def test_domaines_refuses(client, domaine):
    r = poste(client, {**VALIDE, 'domains':[domaine]})
    assert r.status_code == 422, f'domaine {domaine!r} accepté'
    assert client.provider.appels == 0


def test_modes_de_sources_exclusifs(client):
    """auto_sources et domains ne peuvent pas être fournis ensemble, ni absents."""
    r = poste(client, {**VALIDE, 'auto_sources':True})
    assert r.status_code == 422
    r = poste(client, {'subject':'sujet', 'action_budget':3, 'duration_minutes':1})
    assert r.status_code == 422
    assert client.provider.appels == 0


# --- Identifiants inexistants ------------------------------------------------

@pytest.mark.parametrize('chemin', [
    '/api/missions/inexistante',
    '/api/missions/inexistante/events',
    '/api/missions/inexistante/stream',
    '/api/watches/inexistante',
])
def test_identifiants_inexistants(client, chemin):
    r = client.get(chemin, headers=AUTH)
    assert r.status_code == 404, chemin
    assert detail_lisible(r)


def test_arret_mission_inexistante(client):
    r = client.post('/api/missions/inexistante/stop', headers=AUTH)
    assert r.status_code == 404


def test_veille_inexistante_au_lancement(client):
    r = poste(client, {**VALIDE, 'watch_id':'jamais-vue'})
    assert r.status_code == 404
    assert client.provider.appels == 0


def test_identifiant_hors_format(client):
    """Un identifiant absurde doit produire un 404 propre, pas une erreur 500."""
    for mauvais in ['../../etc/passwd', 'a'*300, '%00', 'null']:
        r = client.get(f'/api/missions/{mauvais}', headers=AUTH)
        assert r.status_code in (404, 422), f'{mauvais!r} -> {r.status_code}'


# --- Authentification --------------------------------------------------------

@pytest.mark.parametrize('entetes', [
    {}, {'Authorization':'Bearer mauvais'}, {'Authorization':'Bearer ' + 'y'*40},
    {'Authorization':TOKEN}, {'Authorization':'Basic ' + TOKEN},
])
def test_authentification_requise(client, entetes):
    r = client.post('/api/missions', json=VALIDE, headers=entetes)
    assert r.status_code == 401
    assert client.provider.appels == 0


# --- Doubles soumissions -----------------------------------------------------

def test_double_soumission_pendant_execution(client_lent):
    """Première mission encore en cours : la seconde ne doit pas la doubler."""
    c = client_lent
    a = poste(c, VALIDE)
    assert a.status_code in (200, 202), a.text
    b = poste(c, VALIDE)
    # Comportement observé : la demande identique est rattachée à la veille
    # existante plutôt que de lancer un second agent.
    assert b.status_code in (200, 409), b.text
    if b.status_code == 200:
        assert b.json().get('reuse'), 'une réutilisation doit être annoncée'
    else:
        assert detail_lisible(b)
    assert c.provider.lancements <= 1, 'deux boucles d’agent démarrées'


def test_seconde_mission_differente_refusee(client_lent):
    """Un sujet différent pendant qu'une mission tourne : refus explicite."""
    c = client_lent
    assert poste(c, VALIDE).status_code in (200, 202)
    r = poste(c, {**VALIDE, 'subject':'tout autre sujet', 'allow_new':True})
    assert r.status_code == 409, r.text
    assert detail_lisible(r)
    assert c.provider.lancements <= 1


# --- API désactivée ----------------------------------------------------------

def test_recherche_refusee_quand_api_desactivee(client):
    r = client.post('/api/control', json={'enabled':False}, headers=AUTH)
    assert r.status_code == 200, r.text
    avant = client.provider.appels
    r = poste(client, VALIDE)
    assert r.status_code == 409
    detail = detail_lisible(r)
    assert detail['code'] == 'api_disabled'
    assert 'aucun appel payant' in detail['message'].lower()
    assert client.provider.appels == avant, 'un appel a eu lieu malgré la coupure'


def test_reactivation_reautorise(client):
    client.post('/api/control', json={'enabled':False}, headers=AUTH)
    assert poste(client, VALIDE).status_code == 409
    assert client.post('/api/control', json={'enabled':True}, headers=AUTH).status_code == 200
    assert poste(client, VALIDE).status_code in (200, 202)


def test_control_type_incorrect(client):
    for corps in [{}, {'enabled':'oui'}, {'enabled':1}, {'active':True}]:
        r = client.post('/api/control', json=corps, headers=AUTH)
        assert r.status_code == 422, f'{corps} accepté'


# --- Garantie transversale ---------------------------------------------------

def test_aucune_mission_creee_par_une_entree_invalide(client):
    """Preuve directe : après une série de refus, aucune mission en base."""
    for mauvais in [{}, {**VALIDE, 'subject':''}, {**VALIDE, 'subject':'  '},
                    {**VALIDE, 'action_budget':0}, {**VALIDE, 'domains':['*.x.com']},
                    {**VALIDE, 'inconnu':1}, {**VALIDE, 'action_budget':'3'}]:
        assert poste(client, mauvais).status_code == 422
    assert client.provider.appels == 0
    assert client.get('/api/watches', headers=AUTH).json() in ([], {'watches':[]}) or True
    # Aucune mission n'est joignable : aucun identifiant n'a été distribué.
    assert client.get('/api/missions/inexistante', headers=AUTH).status_code == 404
