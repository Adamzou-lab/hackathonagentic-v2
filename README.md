# Lockin — Le Métronome

Agent de veille web d’Adam et Panaki. Choisissez un sujet, votre budget et des sources automatiques ou manuelles ; suivez la recherche en direct et arrêtez-la à tout moment.

## Démarrer en moins de 5 minutes

**À avoir avant de commencer :** [Python 3.12 ou plus récent](https://www.python.org/downloads/), Git et une connexion Internet. Pour une vraie recherche, il faut aussi une clé API Anthropic avec du crédit et accès à la recherche web.

### 1. Télécharger

```sh
git clone --branch main --single-branch https://github.com/Adamzou-lab/hackathonagentic-v2.git
cd hackathonagentic-v2
```

La version intégrée et déployable est sur **main**. Si le dépôt est privé, votre compte GitHub doit y avoir accès.

### 2. Lancer

**macOS / Linux :**

```sh
python3 start.py
```

**Windows :**

```powershell
py start.py
```

Le lanceur demande votre clé Anthropic à la première utilisation (saisie masquée), prépare Python, installe les dépendances, crée la configuration et ouvre le navigateur. **Pas de Docker, de commande d’installation supplémentaire ni de fichier à créer à la main.** Le premier téléchargement dépend de votre connexion.

### 3. Tester une recherche

Dans la page ouverte :

1. Saisir **« Nouveautés sur les agents IA chez Anthropic »**.
2. Ajouter le domaine **www.anthropic.com**, choisir **10 actions** et **2 minutes**.
3. Ouvrir **.lockin/operator-token.txt** et copier son contenu dans le champ « jeton opérateur ». Ce fichier contient uniquement le jeton de connexion, jamais la clé Anthropic. Inutile d’ouvrir .env pendant la démonstration.
4. Cliquer sur **Lancer**, observer le journal et les résultats, puis tester **Arrêter l’agent**.

Les recherches réelles consomment du crédit Anthropic. Une recherche peut finir sans constat exploitable : le journal permet de comprendre son déroulement.

**Pour relancer :** refaire uniquement `python3 start.py` (Windows : `py start.py`). La clé et les données sont conservées. Garder le terminal ouvert ; **Ctrl+C** arrête le serveur.

### Juste voir l’interface, sans clé API

```sh
python3 start.py --demo
```

Sous Windows : `py start.py --demo`. Le bandeau indique les **données simulées** : ce mode ne consomme aucun crédit et ne valide pas la chaîne réelle du checkpoint.

## Un problème ?

| Problème | Solution |
| --- | --- |
| Python introuvable ou trop ancien | Installer Python 3.12+ ; sous Windows, activer « Add Python to PATH ». |
| Installation des dépendances en échec | Vérifier Internet et relancer la même commande. Sous Linux, installer le paquet venv correspondant à votre Python si nécessaire. |
| Le navigateur ne s’ouvre pas | Ouvrir http://127.0.0.1:8000/ manuellement. |
| Port déjà occupé | Lancer `python3 start.py --port 8001` (Windows : `py start.py --port 8001`). |
| Jeton incorrect (401) | Copier le contenu de .lockin/operator-token.txt après lancement. |
| Clé fournisseur refusée | Corriger ANTHROPIC_API_KEY dans .env, vérifier crédit et accès à la recherche web, puis relancer. |
| Une mission existe déjà (409) | L’arrêter depuis son écran ou attendre son échéance. |
| Page refusée | Vérifier l’hôte exact autorisé ; robots.txt et les redirections peuvent entraîner un refus. |

Le fichier **.env contient vos secrets**, reste local et est ignoré par Git. Le journal est dans **data/lockin.db**. Un redémarrage conserve les résultats, mais ne relance pas automatiquement une mission interrompue.

## Alternative Docker

Avec Docker et Compose v2 démarrés :

```sh
cp .env.example .env
```

Renseigner ANTHROPIC_API_KEY et remplacer LOCKIN_ACCESS_TOKEN par un jeton aléatoire de 32 caractères minimum (générable avec `openssl rand -hex 32`). Puis :

```sh
docker compose up --build -d
```

Ouvrir http://localhost:8000/. Logs : `docker compose logs --tail=100 lockin`. Arrêt : `docker compose down` ; ne pas ajouter `-v` pour conserver les données.

## Configuration et vérifications

Aucune clé supplémentaire pour la recherche web : elle utilise Anthropic.

| Variable | Usage | Valeur par défaut |
| --- | --- | --- |
| ANTHROPIC_API_KEY | Modèle et recherche web | Demandée au premier lancement |
| LOCKIN_ACCESS_TOKEN | Authentification des missions | Généré par le lanceur |
| LOCKIN_MODEL | Modèle | claude-haiku-4-5 |
| LOCKIN_DB_PATH | Journal SQLite | data/lockin.db |
| LOCKIN_INCIDENT_PATH | Journal de secours si SQLite disparaît | Chemin de la base suivi de .incidents.jsonl |

http://localhost:8000/health doit répondre `{"status":"ok","service":"Lockin"}`. Cette sonde vérifie la disponibilité du stockage, sans appel Anthropic ; elle ne valide pas la clé. Une perte du stockage ou un arrêt non confirmé donne HTTP 503.

Tests backend sans appels Anthropic après installation : `.venv/bin/python -m pytest -q` ; sous Windows : `.venv\Scripts\python.exe -m pytest -q`.

## Bonus palier 5 : coût affiché

L'écran de suivi affiche le coût estimé de la dernière requête Anthropic terminée,
avec ses jetons d'entrée/sortie et le nombre de recherches web facturées. Le calcul
reste côté serveur et utilise les métriques retournées par Anthropic. Les tarifs
publics configurés pour Haiku 4.5 sont de 1 USD/Mjeton en entrée, 5 USD/Mjeton en
sortie, 1,25 USD/Mjeton écrit en cache, 0,10 USD/Mjeton lu depuis le cache et
0,01 USD par recherche web. L'interface marque le montant comme une estimation ;
si le tarif du modèle est inconnu, elle affiche « Indisponible » au lieu d'inventer.

Le mode démo montre également cette carte avec des valeurs explicitement simulées.
Les tests vérifient le calcul, le cas d'un modèle inconnu, la persistance dans
l'instantané API et la présence de l'élément dans l'interface. Voir [PALIER5.md](PALIER5.md).

## Documents du projet

- [SPEC.md](SPEC.md) : problème, user stories et hors scope.
- [MENACES.md](MENACES.md) : modèle de menace.
- [API.md](API.md) : contrat HTTP.
- [OUTILS.md](OUTILS.md) : signatures des outils.
- [PALIER4_CONTRAT.md](PALIER4_CONTRAT.md) : événements d'arrêt, de panne et de récupération pour Claude et Panaki.
- [RECETTE_PALIER4.md](RECETTE_PALIER4.md) : provoquer une coupure dans un processus de test isolé et montrer les preuves.

## Organisation Git

Contributions sur `adam` et `panaki`, intégration par pull request vers `dev`, puis validation vers `main`.


## Retrouver et actualiser ses veilles

« Mes veilles » donne accès aux résultats conservés et à chaque exécution avec ses
preuves. Une demande identique récente réutilise les résultats sans nouveau crédit
API. « Actualiser » recherche les nouveautés dans la même fiche, avec un nouveau
budget et un contexte factuel borné. Les sujets proches font l'objet d'une
proposition à confirmer.

Le mode Sources automatiques découvre puis sélectionne jusqu'à cinq domaines
pertinents, en privilégiant les publications d'origine. Les domaines restent
visibles et modifiables pour l'actualisation suivante. La préparation utilise deux
actions ; elle ne garantit pas un classement objectif de fiabilité. Le mode manuel
reste disponible. La démonstration `?demo` illustre ces parcours sans appels API.
