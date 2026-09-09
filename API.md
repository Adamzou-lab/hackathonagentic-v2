# Lockin — contrat API du socle

Backend FastAPI, un processus Uvicorn et une mission active maximum. Suivi SSE authentifié avec reprise ; polling de secours toutes les secondes. Les missions et événements sont persistés en SQLite. Un redémarrage marque les missions interrompues comme `failed`, sans reprise automatique. Le [contrat du palier 4](PALIER4_CONTRAT.md) précise les opérations, pannes, arrêts et traces de récupération.

## Configuration destinée à Claude

Python 3.12 ou supérieur. Installation : `pip install -r requirements.txt`. Lancement : `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`. Tests : `python -m pytest tests -q`.

Variables uniquement côté serveur :

| Variable | Valeur / usage |
| --- | --- |
| `ANTHROPIC_API_KEY` | Obligatoire pour lancer une vraie mission. Jamais envoyée au navigateur. |
| `LOCKIN_MODEL` | `claude-haiku-4-5` par défaut ; modèle de votre compte compatible avec outils et web search. |
| `LOCKIN_ACCESS_TOKEN` | Obligatoire, 32 caractères minimum. Secret d'accès opérateur distinct de la clé Anthropic. En-tête `Authorization: Bearer …` sur toutes les routes `/api/`. |
| `LOCKIN_DB_PATH` | `data/lockin.db` par défaut. Monter `data/` en volume persistant dans Docker. |
| `LOCKIN_INCIDENT_PATH` | Optionnel : journal de secours indépendant de SQLite ; par défaut le chemin de la base suivi de `.incidents.jsonl`. |

Le fichier `.env` n'est pas chargé implicitement par Python : Compose doit injecter ces variables (`env_file`). Pour le lancement sans Docker, les exporter explicitement. Ne pas commiter les secrets. Le VPS doit terminer HTTPS via son reverse proxy. Ne pas exposer plusieurs workers/instances sur la même base : la gestion de la tâche active est locale au processus.

La recherche passe par l'outil web search Anthropic `web_search_20250305`, limité à une recherche par invocation, puis les pages sont lues par notre outil local contrôlé. Pas de clé Tavily requise. Web search doit être disponible sur le compte Anthropic ; sinon l'erreur est visible. Recherche et décision consomment toutes deux le compteur d'appels modèle. Les opérations internes de recherche du fournisseur ne sont pas observables comme des requêtes locales.

## Routes

- `GET /health` : public, `{"status":"ok","service":"Lockin"}` ; vérifie aussi le stockage, sans valider la clé fournisseur. HTTP 503 si le stockage disparaît ou si une annulation n'est pas confirmée.
- `GET /api/config` : configuration disponible et limites publiques, sans secrets.
- `GET /api/incidents` : dernières traces de secours assainies (100 maximum), authentifiées, consultables même si SQLite est indisponible.
- `POST /api/missions` : crée et démarre une mission, HTTP 202 ; renvoie l'instantané ci-dessous.
- `GET /api/missions/{id}` : instantané courant, HTTP 200.
- `POST /api/missions/{id}/stop` : arrêt idempotent, renvoie l'instantané. `stopping` signifie demande persistée, `stopped` confirme l'arrêt du moteur. Si l'annulation reste sans confirmation, `failed / cancellation_unconfirmed` bloque toute nouvelle mission.
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
  "last_request_cost":{"model":"claude-haiku-4-5","currency":"USD",
    "amount_usd":0.01042,"estimated":true,"input_tokens":170,
    "output_tokens":50,"cache_creation_input_tokens":0,
    "cache_read_input_tokens":0,"web_search_requests":1},
  "total_estimated_cost_usd":0.02108,
  "current_action":"read_page", "error":null,
  "sources":[], "findings":[], "events":[],
  "summary":{"partial":true,"text":"Aucun résultat exploitable pour le moment."}
}
```

`last_request_cost` décrit uniquement la dernière réponse fournisseur terminée.
Le montant inclut les jetons d'entrée, de sortie et de cache ainsi que les appels
à la recherche web signalés par Anthropic. Il s'agit d'une estimation en USD au
tarif public de Haiku 4.5, pas d'une facture. Pour un modèle sans tarif configuré,
les compteurs restent visibles et `amount_usd` vaut `null` : aucun montant n'est inventé.

États : `pending`, `running`, `stopping`, `stopped`, `refused`, `completed`, `budget_exhausted`, `deadline_reached`, `failed`. Arrêter le polling aux états terminaux, jamais à `stopping`. Les jauges représentent `actions_used/action_budget` et `elapsed_seconds/duration_seconds`, pas un pourcentage de connaissances trouvées.

Source : `source_id`, `url`, `title`, `retrieved_at`, `published_at` nullable, `status` (`ok` ou `error`), `error` nullable. Constat : `finding_id`, `title`, `summary`, `developer_impact`, `evidence` (liste de `source_id` et `quote`), `event_date` nullable, `date_status`, `confidence`, `caveats`. Événement : `seq`, `at`, `kind`, `data`. Rendre toutes les valeurs comme texte (`textContent`), jamais comme HTML externe ; ne transformer en liens que les URL HTTPS validées.

Erreurs : `{"detail":"message"}` pour 401/404/503 ; certains 409 de rapprochement portent un objet détaillé (voir ci-dessous). 422 contient les erreurs de validation FastAPI. 409 peut signaler une mission déjà active. 503 signale une configuration absente, un stockage indisponible ou un arrêt non confirmé. Pour le stockage, la réponse ajoute `dependency: "sqlite"` et `reaction: "stop"`. Une panne fournisseur après lancement devient `failed` avec code nettoyé et résultats conservés, sans nouvelle tentative payante automatique.

## Limites du socle

Pas de garantie de vérité ou d'exhaustivité, pas de reprise automatique après panne, pas de détection exhaustive d'injection. Date de publication éventuellement inconnue. Les pages bloquées, privées, trop grosses ou non HTML sont refusées. Une synthèse à l'arrêt est assemblée sans nouvel appel au modèle. Plafonds fixes : 60 appels modèle, 200 requêtes réseau locales, 2 tentatives par URL et contexte modèle borné. Le moteur borne les appels modèle à 45 secondes et les lectures/DNS à 15 secondes, sous la durée restante de mission ; les transports ont aussi leurs propres délais, parfois plus courts. La lecture des sources respecte robots.txt de façon conservatrice ; refus si ses règles ne sont pas récupérables (404 signifie absence de règles). Les redirections des documents sont refusées dans ce socle avant de les suivre ; utiliser les URL finales des résultats. Seules les redirections de robots.txt sont suivies avec contrôle de domaine et de résolution réseau.

La qualification de source « officielle » reste le choix de l'opérateur dans la liste de domaines ; le serveur ne peut pas l'attester automatiquement. Tests automatisés avec fournisseurs substitués : ne pas les présenter comme une validation réelle de la clé Anthropic ou comme une démonstration de 30 minutes.

## Flux progressif (palier 3)

### Route

`GET /api/missions/{id}/stream` · `Content-Type: text/event-stream`

Authentification identique aux autres routes `/api/` : en-tête `Authorization: Bearer <LOCKIN_ACCESS_TOKEN>`. **Le jeton ne passe jamais par l'URL** : il finirait dans les journaux du serveur, l'historique du navigateur et le `Referer`.

Conséquence pour le frontend : `EventSource` **ne convient pas**, il ne permet pas d'ajouter un en-tête. Utiliser `fetch` en lecture de flux (exemple plus bas).

Réponses : `401` sans jeton ou avec un mauvais jeton, `404` si la mission n'existe pas, `503` si `LOCKIN_ACCESS_TOKEN` est absent ou trop court. La route est **en lecture seule** : s'y connecter, se déconnecter ou se reconnecter ne lance jamais de mission et n'en modifie aucune.

### Deux natures d'évènements, à ne jamais confondre

| Nature | `event:` | Porte un `id:` | Rejoué après coupure | Fait foi |
| --- | --- | --- | --- | --- |
| Journal persisté | `journal` | oui, le `seq` | oui | **oui** |
| Fragment provisoire | `draft` | non | non | non |
| Fin de flux | `end` | non | non | oui |

Un `draft` décrit ce que le fournisseur est en train d'écrire. Il est incomplet par nature, il n'est jamais exécuté, et il ne doit servir qu'à l'affichage. **Aucune décision, aucun compteur, aucun état ne doit être dérivé d'un `draft`.** Tout ce qui compte arrive en `journal`.

### Format

```
id: 42
event: journal
data: {"mission_id":"…","seq":42,"at":"2026-09-07T…","kind":"action_started",
       "data":{"tool":"read_page","action_number":3,"parameters":{…}}}

event: draft
data: {"mission_id":"…","phase":"tool_input","block":0,"partial_json":"{\"url\": \"https://a"}

event: end
data: {"mission_id":"…","status":"completed","last_seq":57}
```

Phases possibles d'un `draft` : `tool_input_started` (le modèle commence à composer un appel, champ `action`), `tool_input` (fragment brut de JSON, champ `partial_json`), `tool_input_complete` (le bloc est clos), `text` (texte visible du modèle, champ `text`).

Le raisonnement interne du modèle n'est **jamais** diffusé : les blocs `thinking` et `signature` sont ignorés à la source, pas filtrés à l'affichage.

Une ligne `: keepalive` est envoyée après 15 secondes sans trafic, pour traverser les proxys. C'est un commentaire SSE, à ignorer côté client.

### Reconnexion et déduplication

Le client renvoie le dernier `seq` reçu dans l'en-tête `Last-Event-ID`. Le serveur reprend strictement après ce numéro. Les `draft` ne sont pas rejoués : ils décrivent un instant révolu.

Déduplication côté client : ignorer tout `journal` dont le `seq` est inférieur ou égal au dernier traité. Les `seq` sont monotones et sans trou pour une mission donnée.

Le flux se termine par `end` dès que la mission atteint un état terminal, après avoir vidé le journal restant. Le client doit alors cesser de se reconnecter.

### Client attendu côté frontend

```js
const res = await fetch(`/api/missions/${id}/stream`, {
  headers: { Authorization: `Bearer ${token}`, ...(lastSeq && {'Last-Event-ID': String(lastSeq)}) },
});
const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
let buffer = '';
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += value;
  const blocks = buffer.split('\n\n');
  buffer = blocks.pop();
  for (const block of blocks) {
    if (block.startsWith(':')) continue;              // keepalive
    const kind = block.match(/^event: (.+)$/m)?.[1];
    const data = JSON.parse(block.match(/^data: (.+)$/m)?.[1] ?? 'null');
    if (kind === 'journal') { lastSeq = data.seq; appliquerJournal(data); }
    else if (kind === 'draft') afficherFragment(data);  // affichage seul
    else if (kind === 'end') return data.status;
  }
}
```

Le polling d'`/api/missions/{id}` reste valable et sert de repli : le flux n'est pas la source de vérité de l'état, la base l'est.

### Limite connue

`search_web` n'est pas diffusé au fil de l'eau. C'est un outil exécuté côté Anthropic dont le résultat arrive d'un bloc : il n'a pas de progression lisible. Seule la décision du modèle, où il compose ses arguments, est diffusée.

### Réutilisation d'une veille récente

`POST /api/missions` renvoie `200` et la mission existante si une demande identique
est déjà en cours ou s'est terminée sans erreur depuis moins de 24 heures.
L'objet `reuse` indique `reason: recent_completed | already_running` et
`window_hours: 24`. Aucun nouvel appel au modèle ni nouvelle mission n'est créé.
Un nouveau lancement conserve la réponse `202`.

Identité : sujet normalisé Unicode NFC, casse et espaces ignorés, même ensemble
de domaines autorisés, même budget d'actions et même durée. Les paraphrases ne
sont pas fusionnées. Les résultats et leur date originale sont conservés ; les
nouvelles publications intervenues depuis ne sont pas recherchées dans cette
fenêtre. Les refus, erreurs, arrêts et résultats limités par budget/durée ne sont
pas réutilisés. La recherche de doublons est persistante en SQLite et protégée
par la même authentification que les missions (un espace opérateur partagé).

## Fiches de veille, actualisations et sources automatiques

`GET /api/watches?query=&limit=50&offset=0` (authentifié) liste les fiches :
`{watches: [{id, subject, created_at, updated_at, latest_mission_id, status,
findings_count, run_count, domains, auto_sources}], total}`. Maximum 100 fiches/page.
`GET /api/watches/{id}` ajoute `findings` agrégés et `runs` (dernière exécution en
premier). Chaque constat porte `entry_id`, `mission_id`, `source_links`, `change`
(new/updated) et, si nécessaire, `previous_versions`. Les snapshots et journaux
originaux restent accessibles via `/api/missions/{id}`.

Champs supplémentaires de `POST /api/missions` :

- `auto_sources` : false par défaut API. Avec true, fournir `domains: []` ;
  le modèle découvre et sélectionne de un à cinq domaines publics pertinents.
- `watch_id` : rattachement explicitement choisi à une fiche existante.
- `force_refresh` : true lance une actualisation même avant 24 h ; un double clic
  pendant une mission identique retrouve toutefois l'exécution en cours.
- `allow_new` : accepte une nouvelle fiche malgré les suggestions de rapprochement.

Sans `watch_id`, un sujet identique avec les mêmes domaines/mode de sources est
rattaché à la plus ancienne fiche correspondante. Budget/durée peuvent évoluer
entre actualisations, mais ne sont pas ignorés pour réutiliser une exécution
récente. Les sujets proches sont repérés localement (comparaison de texte, aucun
appel modèle) : réponse 409 `detail: {code: similar_watches, candidates: [...]}`.
L'opérateur confirme une fiche ou choisit de créer une veille distincte. Ce repérage
est une suggestion approximative, pas une preuve d'identité sémantique.

Une actualisation reçoit de nouveaux compteurs et une nouvelle date. `update_since`
correspond à la dernière exécution terminée sans erreur ; `known_findings` contient
au plus 20 constats et 12 000 caractères avec références, sans anciens journaux ni
pages complètes. Une réduction des domaines manuels retire aussi le contexte issu
d'autres domaines. La découverte automatique refiltre ce contexte après sélection.

`save_finding` accepte `change: new | update | duplicate` et `related_finding_id`
(entry_id connu, requis pour update/duplicate). Les preuves doivent être relues
dans la nouvelle exécution. Les doublons reconnus ne grossissent pas la fiche ;
une évolution conserve l'historique. Le rapprochement sémantique reste imparfait.

Actions supplémentaires : `discover_sources({query})` renvoie jusqu'à 10 candidats
structurés d'une recherche réelle ; `select_sources({sources:[{domain,reason}]})`
autorise uniquement de 1 à 5 candidats, DNS public vérifié. Le lecteur revérifie le
DNS à la connexion et respecte robots.txt. Aucun outil de lecture n'est autorisé
avant sélection. Une erreur de découverte termine la mission avec sa trace.
Cette préparation consomme deux actions et quatre appels modèle avant la première
recherche documentaire. Elle reste dans le budget global, sans appels cachés.
