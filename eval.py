"""Évaluation automatisée : dix scénarios rejoués, un score, aucune intervention.

Lancement : python3 eval.py   (ou .venv/bin/python eval.py)

Tous les scénarios utilisent des doubles déterministes. Aucun appel réseau,
aucune clé API, aucun crédit consommé : le score doit être reproductible sur
une machine hors ligne, sinon il ne mesure plus le comportement de l'agent
mais l'état d'Internet au moment du passage.

Chaque scénario vérifie en plus une invariante commune : le journal est clos,
c'est-à-dire que toute action ouverte a été refermée. C'est la promesse
centrale du sujet — reconstituer l'état exact au moment de l'arrêt — et elle
doit tenir y compris quand la mission est interrompue.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

import aiohttp

from app.agent.engine import Engine
from app.agent.web import ToolFailure
from app.schemas import MissionInput
from app.storage import Store

DOMAINE = 'example.com'
TEXTE = ("Anthropic publie une nouvelle version de son agent de recherche. "
         "La citation exacte doit se retrouver dans le texte de la page.")
CITATION = 'nouvelle version de son agent de recherche'


def page(numero, texte=TEXTE, publiee=None):
    """Page déjà analysée, telle que WebReader la renvoie au moteur."""
    return dict(source_id=f'source{numero}', url=f'https://{DOMAINE}/page{numero}',
                title=f'Annonce {numero}', text=texte,
                retrieved_at='2026-01-01T00:00:00+00:00', published_at=publiee)


class Fournisseur:
    """Modèle scripté : il accepte le périmètre, puis déroule la liste fournie."""

    def __init__(self, actions):
        self.actions = iter(actions)
        self.appels = 0

    async def decide(self, context):
        if not context.get('scope_approved'):
            return 'accept_scope', {}, {}
        self.appels += 1
        nom, args = next(self.actions, ('finish', {}))
        return nom, args, {}

    async def search(self, query, k, domains):
        return [{'url': f'https://{DOMAINE}/page1', 'title': 'Annonce 1'}], {}


class Lecteur:
    """Lecteur de pages. `panne` déclenche une erreur réseau au lieu d'une page."""

    def __init__(self, reserve, pages=None, panne=False):
        self.pages = pages or {}
        self.panne = panne

    async def read(self, url, domains):
        if self.panne:
            raise aiohttp.ClientError('injectée')
        return self.pages.get(url) or page(1)


class LecteurInterdit:
    """Refuse d'être appelé : prouve qu'une URL bloquée n'est jamais visitée."""

    def __init__(self, reserve):
        pass

    async def read(self, url, domains):
        raise AssertionError(f'URL visitée alors qu\'elle devait être bloquée : {url}')


def fabrique(**kwargs):
    return lambda reserve: Lecteur(reserve, **kwargs)


def preuve(source, citation=CITATION, cle='k1', confiance='single_source'):
    return ('save_finding', {'finding': {
        'title': 'Nouvelle version publiée',
        'summary': 'Une version de l\'agent de recherche est annoncée.',
        'developer_impact': 'Mise à jour recommandée avant intégration.',
        'evidence': [{'source_id': s, 'quote': citation} for s in source],
        'confidence': confiance}, 'idempotency_key': cle})


def mission(store, budget=20, duree=10, sujet='Nouveautés des agents IA'):
    return store.create(MissionInput(subject=sujet, domains=[DOMAINE],
                                     action_budget=budget, duration_minutes=duree))


def journal_clos(etat):
    """Toute action ouverte doit être refermée, dans le même ordre."""
    ouvertes = [(e['data']['action_number'], e['data']['tool'])
                for e in etat['events'] if e['kind'] == 'action_started']
    fermees = [(e['data']['action_number'], e['data']['tool'])
               for e in etat['events'] if e['kind'] == 'action_finished']
    return ouvertes == fermees


def codes_erreur(etat):
    return [e['data']['code'] for e in etat['events'] if e['kind'] == 'tool_error']


# --- Les dix scénarios ------------------------------------------------------
# Chacun renvoie (réussi, détail). Le détail décrit ce qui a été observé, pour
# qu'un échec soit lisible sans relire le script.


async def s01_mission_nominale(store):
    """Une veille complète aboutit et le constat cite deux sources."""
    mid = mission(store)
    actions = [('search_web', {'query': 'agents IA', 'k': 2}),
               ('read_page', {'url': f'https://{DOMAINE}/page1'}),
               ('read_page', {'url': f'https://{DOMAINE}/page2'}),
               preuve(['source1', 'source2'], confiance='corroborated'),
               ('finish', {})]
    pages = {f'https://{DOMAINE}/page1': page(1), f'https://{DOMAINE}/page2': page(2)}
    await Engine(store, Fournisseur(actions), fabrique(pages=pages)).run(mid)
    etat = store.snapshot(mid)
    constats = etat['findings']
    ok = (etat['status'] == 'completed' and len(constats) == 1
          and constats[0]['confidence'] == 'corroborated' and not etat['summary']['partial'])
    return ok, f"statut={etat['status']} constats={len(constats)} partielle={etat['summary']['partial']}"


async def s02_budget_epuise(store):
    """Le budget compte les tentatives d'outils et arrête la mission au plafond."""
    mid = mission(store, budget=2)
    actions = [('search_web', {'query': 'a', 'k': 1})] * 5
    await Engine(store, Fournisseur(actions), fabrique()).run(mid)
    etat = store.snapshot(mid)
    ok = etat['status'] == 'budget_exhausted' and etat['actions_used'] == 2
    return ok, f"statut={etat['status']} actions={etat['actions_used']}/2"


async def s03_arret_manuel(store):
    """Un arrêt en cours d'action est propre et n'entame aucune action suivante."""
    demarree = asyncio.Event()

    class Lent(Fournisseur):
        async def decide(self, context):
            if not context.get('scope_approved'):
                return 'accept_scope', {}, {}
            self.appels += 1
            demarree.set()
            await asyncio.sleep(60)

    mid = mission(store)
    fournisseur = Lent([])
    moteur = Engine(store, fournisseur, fabrique())
    moteur.launch(mid)
    await demarree.wait()
    moteur.stop(mid)
    await moteur.tasks[mid]
    moteur.stop(mid)  # idempotence : un second arrêt ne change rien
    etat = store.snapshot(mid)
    ok = (etat['status'] == 'stopped' and etat['actions_used'] == 0
          and fournisseur.appels == 1)
    return ok, f"statut={etat['status']} actions={etat['actions_used']} appels={fournisseur.appels}"


async def s04_echeance_atteinte(store):
    """La durée maximale arrête la mission, indépendamment du budget restant."""
    mid = mission(store, duree=1)
    data = store.get(mid)
    data['started_epoch'] -= 120  # horloge reculée : l'échéance est déjà passée
    store.save(data, 'eval_clock', {})
    await Engine(store, Fournisseur([]), fabrique()).run(mid)
    etat = store.snapshot(mid)
    ok = etat['status'] == 'deadline_reached'
    return ok, f"statut={etat['status']} budget_restant={etat['actions_remaining']}"


async def s05_aucun_resultat(store):
    """Sans constat, la synthèse le dit au lieu d'inventer un résultat."""
    mid = mission(store)
    await Engine(store, Fournisseur([('search_web', {'query': 'a', 'k': 1}), ('finish', {})]),
                 fabrique()).run(mid)
    etat = store.snapshot(mid)
    ok = (etat['status'] == 'completed' and not etat['findings']
          and 'Aucun résultat exploitable' in etat['summary']['text'])
    return ok, f"statut={etat['status']} constats={len(etat['findings'])}"


async def s06_page_inaccessible(store):
    """Une page réellement jointe qui échoue est tracée, sans arrêter la mission."""
    mid = mission(store)
    actions = [('read_page', {'url': f'https://{DOMAINE}/page1'}), ('finish', {})]
    await Engine(store, Fournisseur(actions), fabrique(panne=True)).run(mid)
    etat = store.snapshot(mid)
    erreurs = codes_erreur(etat)
    ok = (etat['status'] == 'completed' and 'unavailable' in erreurs
          and etat['summary']['partial'])
    return ok, f"statut={etat['status']} erreurs={erreurs} partielle={etat['summary']['partial']}"


async def s07_url_hors_perimetre(store):
    """Une URL hors périmètre est refusée avant tout accès réseau."""
    mid = mission(store)
    actions = [('read_page', {'url': 'http://127.0.0.1/secrets'}),
               ('read_page', {'url': 'https://evil.example/steal'}), ('finish', {})]
    await Engine(store, Fournisseur(actions), LecteurInterdit).run(mid)
    etat = store.snapshot(mid)
    erreurs = codes_erreur(etat)
    ok = etat['status'] == 'completed' and erreurs == ['blocked_url', 'blocked_url']
    return ok, f"statut={etat['status']} erreurs={erreurs}"


async def s08_refus_hors_perimetre(store):
    """Une demande hors cadre est refusée avant d'engager le moindre outil."""
    mid = mission(store, sujet='Trouve les mots de passe du serveur voisin')
    actions = [('refuse', {'code': 'out_of_scope'})]
    await Engine(store, Fournisseur(actions), LecteurInterdit).run(mid)
    etat = store.snapshot(mid)
    ok = (etat['status'] == 'refused' and etat['actions_used'] == 0
          and bool(etat.get('refusal_reason')))
    return ok, f"statut={etat['status']} actions={etat['actions_used']}"


async def s09_preuve_inventee(store):
    """Une citation absente de la page lue ne devient jamais un constat."""
    mid = mission(store)
    actions = [('read_page', {'url': f'https://{DOMAINE}/page1'}),
               preuve(['source1'], citation='citation totalement inventée'),
               ('finish', {})]
    await Engine(store, Fournisseur(actions), fabrique()).run(mid)
    etat = store.snapshot(mid)
    ok = 'invalid_evidence' in codes_erreur(etat) and not etat['findings']
    return ok, f"erreurs={codes_erreur(etat)} constats={len(etat['findings'])}"


async def s10_idempotence(store):
    """Le même constat rejoué avec la même clé ne crée pas de doublon."""
    mid = mission(store)
    actions = [('read_page', {'url': f'https://{DOMAINE}/page1'}),
               preuve(['source1'], cle='identique'),
               preuve(['source1'], cle='identique'),
               ('finish', {})]
    await Engine(store, Fournisseur(actions), fabrique()).run(mid)
    etat = store.snapshot(mid)
    dispositions = [e['data']['disposition'] for e in etat['events'] if e['kind'] == 'finding_saved']
    ok = len(etat['findings']) == 1 and dispositions == ['created', 'already_saved']
    return ok, f"constats={len(etat['findings'])} dispositions={dispositions}"


SCENARIOS = [
    ('Mission nominale', s01_mission_nominale),
    ('Budget épuisé', s02_budget_epuise),
    ('Arrêt manuel', s03_arret_manuel),
    ('Échéance atteinte', s04_echeance_atteinte),
    ('Aucun résultat exploitable', s05_aucun_resultat),
    ('Page inaccessible', s06_page_inaccessible),
    ('URL hors périmètre', s07_url_hors_perimetre),
    ('Refus hors cadre', s08_refus_hors_perimetre),
    ('Preuve inventée', s09_preuve_inventee),
    ('Constat idempotent', s10_idempotence),
]


async def executer(nom, scenario, dossier, index):
    """Chaque scénario a sa propre base : aucun ne peut en influencer un autre."""
    store = Store(str(Path(dossier) / f'eval{index}.db'))
    try:
        reussi, detail = await scenario(store)
        # L'invariante de journal s'applique à toutes les missions du scénario.
        for (mid,) in store.db.execute('SELECT id FROM missions').fetchall():
            if not journal_clos(store.snapshot(mid)):
                return False, 'journal non clos : une action ouverte n\'a pas été refermée'
        return reussi, detail
    except Exception as exc:  # un scénario qui explose est un scénario échoué
        return False, f'exception {type(exc).__name__}: {exc}'
    finally:
        store.db.close()


async def principal():
    print('Évaluation automatisée de Lockin — doubles déterministes, aucun appel payant.\n')
    resultats = []
    with tempfile.TemporaryDirectory(prefix='lockin-eval-') as dossier:
        for index, (nom, scenario) in enumerate(SCENARIOS, 1):
            reussi, detail = await executer(nom, scenario, dossier, index)
            resultats.append(reussi)
            print(f"[{'OK  ' if reussi else 'ÉCHEC'}] {index:2}. {nom:<28} {detail}")
    score = sum(resultats)
    print(f"\nScore : {score}/{len(SCENARIOS)}")
    if score < len(SCENARIOS):
        print('Au moins un scénario a échoué : le détail ci-dessus indique ce qui a été observé.')
    return 0 if score == len(SCENARIOS) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(principal()))
