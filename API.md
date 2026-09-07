# Lockin — contrat API du socle

Backend FastAPI, un processus Uvicorn et une mission active maximum. Polling toutes les secondes ; pas de SSE requis. Les missions et événements sont persistés en SQLite. Un redémarrage marque les missions interrompues comme `failed`, sans reprise automatique.

## Configuration destinée à Claude

Python 3.12 ou supérieur. Installation : `pip install -r requirements.txt`. Lancement : `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`. Tests : `python -m pytest tests -q`.

Variables uniquement côté serveur :

| Variable | Valeur / usage |
| --- | --- |
| `ANTHROPIC_API_KEY` | Obligatoire pour lancer une vraie mission. Jamais envoyée au navigateur. |
| `LOCKIN_MODEL` | `claude-haiku-4-5` par défaut ; modèle de votre compte compatible avec outils et web search. |
| `LOCKIN_ACCESS_TOKEN` | Obligatoire, 32 caractères minimum. Secret d'accès opérateur distinct de la clé Anthropic. En-tête `Authorization: Bearer …` sur toutes les routes `/api/`. |
| `LOCKIN_DB_PATH` | `data/lockin.db` par défaut. Monter `data/` en volume persistant dans Docker. |

Le fichier `.env` n'est pas chargé implicitement par Python : Compose doit injecter ces variables (`env_file`). Pour le lancement sans Docker, les exporter explicitement. Ne pas commiter les secrets. Le VPS doit terminer HTTPS via son reverse proxy. Ne pas exposer plusieurs workers/instances sur la même base : la gestion de la tâche active est locale au processus.

La recherche passe par l'outil web search Anthropic `web_search_20250305`, limité à une recherche par invocation, puis les pages sont lues par notre outil local contrôlé. Pas de clé Tavily requise. Web search doit être disponible sur le compte Anthropic ; sinon l'erreur est visible. Recherche et décision consomment toutes deux le compteur d'appels modèle. Les opérations internes de recherche du fournisseur ne sont pas observables comme des requêtes locales.

## Routes

- `GET /health` : public, `{"status":"ok","service":"Lockin"}` ; prouve que le serveur répond, pas que la clé fournisseur est valide.
- `GET /api/config` : configuration disponible et limites publiques, sans secrets.
- `POST /api/missions` : crée et démarre une mission, HTTP 202 ; renvoie l'instantané ci-dessous.
- `GET /api/missions/{id}` : instantané courant, HTTP 200.
- `POST /api/missions/{id}/stop` : arrêt idempotent, renvoie l'instantané. L'affichage peut passer par `stopping`, puis `stopped` au prochain polling.
- `GET /api/missions/{id}/events` : liste complète des événements bornée par les budgets de la mission.
- `/` : sert `app/static/index.html` s'il existe ; sinon redirige vers `/docs` pour tester le socle. Les assets sont sous `/static/`.

L'interface demande le **jeton opérateur Lockin**, jamais la clé Anthropic. Le garder en mémoire de la page, pas dans l'URL ni dans un fichier JS. Cela protège les appels payants sur VPS. Les appels API restent de même origine ; pas de CORS ouvert.

### Création de mission

```json
{"subject":"Nouveautés des frameworks d'IA agentique","domains":["www.anthropic.com","openai.com"],"action_budget":20,"duration_minutes":10}
```

Sujet : 1–500 caractères. De 1 à 5 noms d'hôtes exacts, sans schéma, chemin ni joker. Les sous-domaines sont explicites. Budget : 1–100 tentatives d'outils. Durée : 1–30 minutes. Validation réelle côté serveur, pas uniquement dans le formulaire.

### Instantané (forme stable)

```json
{
  "id":"identifiant-opaque", "subject":"Nouveautés des frameworks d'IA agentique",
  "domains":["www.anthropic.com","openai.com"],
  "status":"running", "created_at":"2026-09-07T12:00:00+00:00", "ended_at":null,
  "action_budget":20, "actions_used":3, "actions_remaining":17,
  "duration_seconds":600, "elapsed_seconds":12, "remaining_seconds":588,
  "model_calls_used":2, "network_requests_used":3,
  "current_action":"read_page", "error":null,
  "sources":[], "findings":[], "events":[],
  "summary":{"partial":true,"text":"Aucun résultat exploitable pour le moment."}
}
```

États : `pending`, `running`, `stopping`, `stopped`, `completed`, `budget_exhausted`, `deadline_reached`, `failed`. Arrêter le polling aux états terminaux, jamais à `stopping`. Les jauges représentent `actions_used/action_budget` et `elapsed_seconds/duration_seconds`, pas un pourcentage de connaissances trouvées.

Source : `source_id`, `url`, `title`, `retrieved_at`, `published_at` nullable, `status` (`ok` ou `error`), `error` nullable. Constat : `finding_id`, `title`, `summary`, `developer_impact`, `evidence` (liste de `source_id` et `quote`), `event_date` nullable, `date_status`, `confidence`, `caveats`. Événement : `seq`, `at`, `kind`, `data`. Rendre toutes les valeurs comme texte (`textContent`), jamais comme HTML externe ; ne transformer en liens que les URL HTTPS validées.

Erreurs : `{"detail":"message"}` pour 401/404/409/503 ; 422 contient les erreurs de validation FastAPI. 409 = mission déjà active. 503 = configuration absente. Une panne fournisseur après lancement devient `failed` avec message nettoyé et résultats conservés.

## Limites du socle

Pas de garantie de vérité ou d'exhaustivité, pas de reprise automatique après panne, pas de détection exhaustive d'injection. Date de publication éventuellement inconnue. Les pages bloquées, privées, trop grosses ou non HTML sont refusées. Une synthèse à l'arrêt est assemblée sans nouvel appel au modèle. Plafonds fixes : 60 appels modèle, 200 requêtes réseau locales, 2 tentatives par URL, 15 secondes par opération et contexte modèle borné. La lecture des sources respecte robots.txt de façon conservatrice ; refus si ses règles ne sont pas récupérables (404 signifie absence de règles). Les redirections des documents sont refusées dans ce socle avant de les suivre ; utiliser les URL finales des résultats. Seules les redirections de robots.txt sont suivies avec contrôle de domaine et de résolution réseau.

La qualification de source « officielle » reste le choix de l'opérateur dans la liste de domaines ; le serveur ne peut pas l'attester automatiquement. Tests automatisés avec fournisseurs substitués : ne pas les présenter comme une validation réelle de la clé Anthropic ou comme une démonstration de 30 minutes.
