# Palier 4 — contrat moteur, journal et incidents

Le moteur persiste les observations avant de les diffuser. Les routes existantes
et le format SSE restent compatibles. Ce contrat est destiné au frontend de
Claude et aux scénarios d'évaluation de Panaki.

## Format et sens des dates

Une entrée du journal conserve `{seq, at, kind, data}`. Le SSE `journal` ajoute
`mission_id`. `seq` est croissant par mission ; `at` est une date ISO UTC avec
fuseau. Une entrée est une observation du serveur, pas une mesure de l'instant
physique d'une coupure réseau ou électrique. L'ordre est donné par `seq`, même
si une correction de l'horloge système modifie l'ordre des dates civiles.

Le moteur produit un `heartbeat` toutes les deux secondes pendant une mission.
Tout événement persistant actualise `last_seen_at` dans l'état. Ce délai est une
cible, pas une garantie si le processus ou sa boucle d'événements sont bloqués.
Un heartbeat SSE du navigateur et ce signe de vie persistant sont distincts.

## Nouveaux événements

| `kind` | `data` | Sens |
| --- | --- | --- |
| `operation_started` | `operation_id`, `dependency`, `operation` | Début d'une attente externe, y compris la décision du modèle |
| `operation_finished` | mêmes identifiants, `outcome`, `code` si pertinent | `success`, `error`, `cancelled` ou `unknown` |
| `dependency_failed` | `dependency`, `operation`, `code`, `reaction`, `operation_id`, `action_number` | Cause assainie détectée ; réaction `stop` ou `continue` |
| `heartbeat` | `status` | Dernier signe de vie enregistré par le moteur |
| `recovery_detected` | `last_seen_at`, `interrupted_at: null`, `reaction: stop` | Mission non terminée trouvée au démarrage ; aucune relance automatique |

Les identifiants de dépendance sont `model_provider`, `web_page`, `dns`, `tool`,
`engine` et `sqlite`. Une `operation` est par exemple `decide`, `search_web`,
`discover_sources`, `select_sources` ou `read_page`.

`operation_id` corrèle une attente et sa fin. `action_number` reste la référence
de l'outil ; il vaut `null` pendant une simple décision. `current_operation` dans
l'état contient `{id, dependency, operation, started_at}` ou `null`.

Les événements existants `action_started` / `action_finished` restent les preuves
des appels d'outils et de leurs arguments/résultats. Une opération externe ne
compte pas comme une action supplémentaire. Les compteurs de modèle et réseau
restent inchangés. Les fragments `draft` ne constituent jamais ces preuves.

## Arrêt volontaire

`POST /api/missions/{id}/stop` reste authentifié. Il est idempotent :

1. `stop_requested`, avec `data.reason: operator`, est persisté avant annulation.
2. L'attente en cours est annulée et son opération ainsi que son éventuel outil
   sont clôturés. Aucun nouvel appel n'est autorisé après la demande.
3. `finished.status: stopped` confirme la fin côté moteur.

Si une dépendance ignore l'annulation, le délai de grâce est de deux secondes
(constat par le heartbeat, donc délai d'observation supplémentaire possible).
`dependency_failed.code: cancellation_unconfirmed` et `finished.status: failed`
signalent un **arrêt non confirmé**. Les opérations ouvertes ont `outcome: unknown`.
De nouvelles missions sont bloquées (503), même si la réponse finit par arriver :
celle-ci est ignorée. La fermeture du moteur n'attend pas indéfiniment. Une
dépendance qui bloque entièrement la boucle Python exige le témoin extérieur ;
le serveur ne peut pas affirmer l'avoir arrêtée.

Lors d'une fermeture normale du serveur, la même séquence utilise
`reason: server_shutdown`. Une réponse réseau perdue à la demande d'arrêt n'est
pas une confirmation d'arrêt. Un appel déjà envoyé peut avoir été traité et
facturé par le fournisseur distant : l'annulation locale ne l'annule pas rétroactivement.

## Réaction aux pannes

| Ressource / code | Réaction |
| --- | --- |
| API modèle : `anthropic_http_401`, `anthropic_http_403`, autres HTTP non 200 | Arrêt `failed`, aucun retry automatique payant |
| API modèle : `anthropic_timeout`, `anthropic_network_error`, `anthropic_key_missing` | Même arrêt ; résultats acquis conservés |
| Réponse invalide : `anthropic_invalid_response`, `anthropic_incomplete_response`, `anthropic_stream_interrupted`, `anthropic_stream_error` | Arrêt ; aucun fragment incomplet exécuté |
| Recherche distante indisponible ou découverte de sources échouée | Arrêt explicite ; pas de nouvelle décision de récupération payante |
| Une page : `unavailable`, `timeout`, `robots_unavailable`, etc. | Erreur retournée au modèle, poursuite possible sous les mêmes budgets ; deux lectures au maximum par URL |
| Appel interdit, arguments invalides, outil désactivé en recette | Refus d'appel tracé, aucune exécution interdite ; poursuite bornée possible |
| SQLite perdu, remplacé ou en erreur | Arrêt du travail, journal de secours indépendant et HTTP 503 ; intervention opérateur requise |

`continue` autorise la boucle à poursuivre sous ses budgets ; cela ne garantit
ni réussite ni nouvel essai sur la même source. Une mission avec erreurs garde
un résultat partiel et n'entre pas dans le cache de réussite de 24 heures.

Un flux fournisseur n'est accepté qu'après sa fin protocolaire confirmée. Aucun
retry HTTP n'est activé. Les dates des erreurs de timeout correspondent à leur
détection, qui peut survenir après la coupure réelle.

## Redémarrage après interruption brutale

Le moteur retrouve la mission, conserve les résultats acquis et produit
`recovery_detected`. Toute opération/action restée ouverte est clôturée avec un
résultat **inconnu**, puis la mission devient `failed`, erreur
`process_interrupted`. Une nouvelle intervention opérateur est nécessaire.
Le serveur ne réexécute jamais automatiquement l'action interrompue.

Une coupure instrumentée dispose d'un témoin indépendant ; voir
[RECETTE_PALIER4.md](RECETTE_PALIER4.md). Les dates de ce témoin ne sont jamais
substituées aux dates du journal de mission.

## Secours en cas de perte du journal principal

Par défaut, les incidents sont écrits dans `<chemin-base>.incidents.jsonl`.
`LOCKIN_INCIDENT_PATH` permet un autre répertoire ou disque. Les écritures sont
synchronisées (`fsync`). Si le secours est lui-même inaccessible, une entrée
JSON assainie est envoyée à stderr ; la durabilité de stderr dépend du lanceur.
Aucune réussite n'est annoncée si tous les supports de journalisation sont perdus.

`GET /api/incidents`, avec le même Bearer opérateur, renvoie les derniers incidents
assainis, même si SQLite est indisponible. Ce journal est distinct : ses entrées
portent `at`, `kind`, `data` et éventuellement `mission_id`, sans `seq` de mission.
Les routes qui utilisent la base et `/health` renvoient HTTP 503 avec
`{detail: "storage_file_missing", dependency: "sqlite", reaction: "stop"}`
(le code varie selon la panne). L'interface ne doit pas confondre ce 503 avec
une mission terminée ou un refus du modèle.

Un marqueur d'identité `.lockin-storage-<empreinte-chemin>.json` est enregistré
à côté du journal de secours pour empêcher la recréation silencieuse d'une base
vide après disparition/remplacement du fichier. Une restauration volontaire
nécessite l'arrêt du serveur, une sauvegarde de la base et des preuves, puis la
réinitialisation explicite du marqueur correspondant avant redémarrage.
Si base, marqueur et preuves disparaissent ensemble, une installation neuve
ne peut pas être distinguée automatiquement de cette perte totale.

## Répartition et validation

Codex : moteur, fournisseur, stockage, routes et recette de coupure externe.
Claude : présentation du journal, supervision UI, reconnexion SSE et tests associés.
Panaki : script des dix scénarios et score. Les tests de robustesse fournis ici
utilisent des doubles annoncés comme tels et des processus locaux ; ils ne
prétendent pas évaluer la décision réelle de Haiku.
