# PARCOURS.md — Le Métronome

Maquette du parcours utilisateur pour l'agent de veille web autonome. Une seule page, cinq zones, dans l'ordre où l'œil les rencontre.

## Maquette (texte)

```
┌─────────────────────────────────────────────────────────────────┐
│  LE MÉTRONOME — Veille web autonome                              │
├─────────────────────────────────────────────────────────────────┤
│  1. CONFIGURATION                                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Sujet de veille        [_________________________________] │  │
│  │ Domaines autorisés     [_________________________________] │  │
│  │                         (un domaine par ligne)              │  │
│  │ Budget d'actions       [ 100 ] tentatives d'outils          │  │
│  │ Durée maximale         [  30 ] minutes                      │  │
│  │                                                               │  │
│  │              [ ▶ Lancer la veille ]                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  2. ÉTAT EN COURS (visible pendant et après l'exécution)         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Statut : ● En cours                                          │  │
│  │ Temps écoulé   : 12 min 51 s  /  30 min      ▓▓▓▓▓░░░░░░░   │  │
│  │ Budget restant : 61 / 100 tentatives         ▓▓▓▓▓▓░░░░░░   │  │
│  │ Sources consultées (5) :                                     │  │
│  │   ✓ https://exemple-source-1.org/article        [ok]        │  │
│  │   ✓ https://exemple-source-2.org/page           [ok]        │  │
│  │   ✗ https://exemple-source-3.org/indisponible   [abandon]   │  │
│  │   ✓ https://exemple-source-4.org/rapport        [ok]        │  │
│  │   … en cours : https://exemple-source-5.org      [en cours] │  │
│  │                                                               │  │
│  │              [ ■ Arrêter l'agent ]                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  3. SYNTHÈSE                                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ ⚠ Synthèse partielle — arrêt manuel à 12 min 51 s            │  │
│  │ Texte de synthèse …                                          │  │
│  │ Sources citées : [1] [2] [4]                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  4. JOURNAL                                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 10:02:01 START     sujet="…" budget=100 échéance=30min       │  │
│  │ 10:02:03 SEARCH    "…" k=5 → 5 résultats        [budget 99]  │  │
│  │ 10:02:06 FETCH     source-1.org/article → ok    [budget 98]  │  │
│  │ 10:02:09 FETCH     source-3.org → timeout (1/2) [budget 97]  │  │
│  │ 10:02:24 FETCH     source-3.org → timeout (2/2) [budget 96]  │  │
│  │ 10:02:24 ABANDON   source-3.org : 2 tentatives atteintes     │  │
│  │ 10:02:31 SAVE      constat #4, 1 preuve         [budget 95]  │  │
│  │ 10:14:52 STOPPING  arrêt demandé, appel en cours borné       │  │
│  │ 10:14:53 STOPPED   budget restant=61, écoulé=12min51s        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Détail des zones

### 1. Saisie et lancement
- **Sujet** : champ texte libre, obligatoire.
- **Domaines autorisés** : liste de domaines racines ; c'est la frontière de ce que l'agent a le droit de consulter. À ne pas confondre avec les destinations techniques (prestataire de recherche, fournisseur de modèle), qui sont configurées côté serveur et n'apparaissent pas ici. Voir `MENACES.md`.
- **Budget d'actions** : nombre de **tentatives d'outils**, pas de pages. Une recherche, une lecture, une sauvegarde et chaque tentative en échec consomment une unité. C'est ce qui rend le compteur honnête : une source qui échoue coûte quand même du budget.
- **Durée maximale** : échéance en minutes, indépendante du budget. L'agent s'arrête au premier des deux atteint.
- **Bouton de lancement** : désactivé tant que sujet, domaines, budget et durée ne sont pas valides.

Les valeurs affichées (100 tentatives, 30 minutes) sont des valeurs de démonstration, pas un réglage technique validé. Les limites de référence sont dans `OUTILS.md`.

### 2. État en cours
- **Statut**, avec le nom technique correspondant dans `OUTILS.md` :

  | Affichage | État technique | Quand |
  | --- | --- | --- |
  | En attente | `pending` | Mission créée, pas encore démarrée |
  | En cours | `running` | L'agent travaille |
  | Arrêt en cours | `stopping` | Arrêt reçu par le serveur, un appel déjà parti est encore borné par son délai |
  | Arrêté (manuel) | `stopped` | Plus aucune action, état final figé |
  | Terminé | `completed` | L'agent a fini de lui-même, sans épuiser budget ni durée |
  | Arrêté (budget épuisé) | `budget_exhausted` | Plus de tentatives disponibles |
  | Arrêté (échéance) | `deadline_reached` | Durée maximale atteinte |
  | Erreur | `failed` | Le journal ne peut plus être écrit, ou panne bloquante |

  La distinction entre « arrêt en cours » et « arrêté » n'est pas cosmétique : entre le clic et l'arrêt effectif, un appel réseau peut être encore en vol. Afficher « arrêté » tout de suite serait un mensonge de quelques secondes.

- **Temps écoulé et échéance** : affichés en permanence, à côté du budget. Ce sont deux limites distinctes.
- **Budget restant** : décroît en temps réel, sans rafraîchir la page.
- **Sources consultées** : liste chronologique, chaque entrée avec son statut (ok, en cours, abandon après deux tentatives).
- **Bouton d'arrêt** : visible pendant l'exécution. Le serveur cesse d'autoriser toute nouvelle action dès qu'il **reçoit** la demande, pas à l'instant du clic : entre les deux il y a le réseau, et nous ne promettons pas ce que nous ne contrôlons pas.
- Après l'arrêt, cette zone **reste affichée** avec l'état final, le budget restant et le temps écoulé.

### 3. Synthèse
- Affichée dès qu'il existe au moins un constat exploitable, même si l'agent tourne encore.
- Marquée **partielle** dans tous les cas où la mission n'est pas allée à son terme : arrêt manuel, budget épuisé, échéance atteinte, ou sources abandonnées après échec. L'absence d'arrêt manuel ne suffit pas à qualifier une synthèse de complète.
- Le cas « aucun résultat exploitable » est affiché explicitement, pas laissé vide. Ne rien avoir trouvé est un résultat valide, pas une panne.
- Chaque affirmation renvoie à une ou plusieurs sources réellement consultées.

### 4. Journal
- Liste chronologique et horodatée : démarrage, recherche, lecture, abandon d'une source, sauvegarde d'un constat, demande d'arrêt, état final.
- Chaque ligne porte le budget restant après l'action, ce qui permet de relire la consommation pas à pas.
- Le journal enregistre les actions et leurs résultats, **pas le raisonnement interne du modèle** (voir `SPEC.md`, exclusion 11). Le rapprochement entre deux sources qui disent la même chose n'est donc pas un événement de journal : c'est un champ du constat sauvegardé (`Confidence` dans `OUTILS.md`).
- Doit permettre de reconstituer l'état exact de l'agent à n'importe quel instant, y compris après un arrêt.

## Hors scope de cette maquette
- Pas d'authentification ni de gestion multi-utilisateur.
- **Pas de tableau de bord multi-missions** : une mission à l'écran à la fois. Les journaux et rapports des missions passées restent conservés et consultables par leur identifiant ; ce que nous excluons, c'est leur réinjection comme contexte du modèle (voir `SPEC.md`, exclusion 1).
- Pas de configuration avancée du modèle (prompt, température) exposée à l'utilisateur.
