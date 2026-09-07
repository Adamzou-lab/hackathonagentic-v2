# Lockin — Le Métronome

Agent de veille web du binôme **Adam et Panaki** : sujet configurable, domaines autorisés, budget d’actions, durée maximale et arrêt manuel. Les constats sourcés et le journal sont conservés dans SQLite.

## Démarrage examinateur — objectif moins de 5 minutes

**Prérequis :** Git, Docker avec Compose v2 et moteur démarré, accès Internet. Pour une **vraie recherche**, prévoir une clé API Anthropic valide avec du crédit et accès à la recherche web. Le temps du premier téléchargement dépend de la connexion.

> Pour le palier 2, cloner explicitement **`adam`**, qui rassemble le backend et l’interface. `main` n’a pas encore été mis à niveau.

### 1. Cloner et préparer la configuration

```sh
git clone --branch adam --single-branch https://github.com/Adamzou-lab/hackathonagentic-v2.git
cd hackathonagentic-v2
cp .env.example .env
```

Si le dépôt est privé, utiliser un compte GitHub ayant accès au dépôt.

### 2. Remplacer deux valeurs dans `.env`

Ouvrir `.env` dans votre éditeur :

- Remplacer `ANTHROPIC_API_KEY` par votre clé Anthropic.
- Remplacer `LOCKIN_ACCESS_TOKEN` par un jeton aléatoire d’au moins 32 caractères. Sur macOS/Linux, le générer avec `openssl rand -hex 32`.

Conserver les deux autres valeurs. **Aucune autre clé de recherche n’est nécessaire.** Ne pas publier `.env`.

| Variable | Usage | Valeur |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Modèle et recherche web Anthropic | Votre clé |
| `LOCKIN_ACCESS_TOKEN` | Accès opérateur aux missions | Votre jeton, 32 caractères minimum |
| `LOCKIN_MODEL` | Modèle utilisé | `claude-haiku-4-5` |
| `LOCKIN_DB_PATH` | Journal SQLite | `data/lockin.db` |

### 3. Lancer et ouvrir

```sh
docker compose up --build -d
docker compose ps
```

Ouvrir **http://localhost:8000/**. L’interface et l’API sont servies ensemble, sans installation frontend supplémentaire.

Vérifier **http://localhost:8000/health** : attendu `{"status":"ok","service":"Lockin"}`. Cette sonde confirme que le serveur répond ; elle ne teste pas la clé Anthropic.

### 4. Vérifier la chaîne réelle

1. Saisir **« Nouveautés sur les agents IA chez Anthropic »**.
2. Autoriser **`www.anthropic.com`**, sans `https://` (nom d’hôte exact).
3. Choisir **10 actions** et **2 minutes**.
4. Saisir le **jeton opérateur `LOCKIN_ACCESS_TOKEN`**, puis lancer. La clé Anthropic reste côté serveur.
5. Observer le journal, les compteurs et les sources ; un constat apparaît lorsqu’une preuve exploitable est enregistrée.
6. Cliquer sur **Arrêter l’agent** pour vérifier l’arrêt et la conservation des résultats, ou attendre la limite.

Les appels réels consomment du crédit Anthropic. Une recherche peut terminer sans constat exploitable ; les erreurs et refus restent visibles dans le journal.

**Aperçu sans clé API :** après démarrage, ouvrir http://localhost:8000/?demo pour manipuler l’interface avec des données simulées. Ce mode est signalé à l’écran, ne fait aucun appel Anthropic et **ne valide pas la chaîne réelle du checkpoint**.

## Sans Docker — macOS / Linux

Prérequis : **Python 3.12 ou supérieur**, Git et accès Internet. Après le clonage et la configuration de `.env` ci-dessus :

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
set -a
. ./.env
set +a
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Garder ce terminal ouvert puis ouvrir http://localhost:8000/. Les commandes `set -a` et `. ./.env` chargent la configuration : l’application ne lit pas automatiquement `.env`. Charger uniquement votre propre fichier. Sous Windows, privilégier Docker ou WSL pour suivre ces commandes.

## En cas de blocage

| Symptôme | Action |
| --- | --- |
| Docker ne répond pas | Démarrer Docker Desktop ou le moteur Docker. |
| Port 8000 occupé | Arrêter l’autre service, ou remplacer le port de gauche dans `compose.yaml` par `8001`, puis ouvrir localhost:8001. |
| Erreur 401 | Recopier exactement le jeton opérateur de `.env`. |
| Erreur 503 | Vérifier la présence de la clé et la longueur du jeton, puis `docker compose up -d --force-recreate`. |
| Erreur fournisseur dans le journal | Vérifier la clé, le crédit et l’accès au modèle/recherche web du compte Anthropic. |
| Mission déjà en cours (409) | Arrêter la mission depuis son écran ou attendre son échéance ; une seule mission active est autorisée. |
| Page refusée | Vérifier l’hôte exact ; robots.txt, adresses privées et redirections de pages peuvent entraîner un refus. |

Voir les logs : `docker compose logs --tail=100 lockin`.

Arrêter : `docker compose down`. Le volume nommé conserve les données. Ne pas ajouter `-v` si vous voulez les garder. Un redémarrage marque les missions interrompues en échec ; il ne les relance pas automatiquement.

## Tests et documents

Tests backend sans appel Anthropic, après installation locale : `.venv/bin/python -m pytest -q`.

- [SPEC.md](SPEC.md) : problème, user stories et hors scope.
- [MENACES.md](MENACES.md) : modèle de menace.
- [API.md](API.md) : contrat HTTP et authentification.
- [OUTILS.md](OUTILS.md) : signatures des outils.

## Organisation Git

- `main` : version stable et démontrable.
- `dev` : intégration du travail du binôme.
- `adam` : travail piloté par Adam.
- `panaki` : travail piloté par Panaki.

Les contributions passent par une pull request de `adam` ou `panaki` vers `dev`, puis de `dev` vers `main` après validation.

Codex et Claude assistent le binôme. Avant chaque intervention, vérifier la branche active et se répartir les fichiers pour éviter les modifications concurrentes.
