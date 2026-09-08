# Palier 4 — arrêt, panne et preuve de coupure

Cette recette concerne une mission réelle exécutée par le moteur et un processus de serveur **isolé pour le test**. Elle ne remplace pas le script d'évaluation de dix scénarios confié à Panaki. L'outil de coupure ne fait aucun appel IA ; une mission utilisant Haiku consomme du crédit comme d'habitude.

## Deux journaux qui ne racontent pas la même chose

- Le **journal de mission** est produit par Lockin. Son champ `at` est l'heure UTC à laquelle le serveur a enregistré une observation. Un `dependency_failed` donne notamment `dependency`, `operation`, `code` et `reaction` (`stop` ou `continue`). L'heure de détection d'un délai dépassé n'est pas l'heure physique de la coupure réseau.
- Le **journal externe de coupure** est produit par `scripts/palier4_fault.py`. Il peut continuer d'écrire lorsque son processus enfant Lockin est mort. Il est séparé du journal de mission, identifié par `source: external_fault_supervisor` et un `session_id`. Il n'est ni une réponse du modèle ni un résultat d'outil.

Lors d'une coupure brutale, le processus mort ne peut pas écrire sa propre heure de mort. Le superviseur écrit et synchronise sur disque (`flush` + `fsync`) `fault_requested` **avant** SIGKILL. Il attend ensuite la confirmation de la sortie de son enfant avec le code SIGKILL, puis écrit `fault_applied`. L'heure physique de l'interruption est bornée par `requested_at` et `applied_at` ; `interrupted_at` reste `null`. Si le processus sort naturellement dans l'intervalle, la recette ne déclare pas un succès de coupure.

Le fichier JSONL conserve les dates UTC avec fuseau et microsecondes. `seq` et `monotonic_ns` donnent l'ordre et les durées dans cette session ; une modification de l'horloge système peut affecter les dates civiles. L'heure de synchronisation disque, l'heure d'application physique du signal et une précision supérieure à celle de l'horloge ne sont pas revendiquées.

## Vérifier le dispositif sans API

Depuis la racine du dépôt, avec l'environnement Python du projet :

```bash
python scripts/palier4_fault.py --log /tmp/lockin-coupure-essai-1.jsonl --after 0.2 -- python -c 'import time; time.sleep(60)'
python -m pytest -q tests/test_fault_checkpoint.py
```

Le premier processus ne fait que dormir : cette commande vérifie le dispositif de coupure, **pas le comportement de Lockin**. Le résultat attendu est `fault_requested`, puis `fault_applied`, un code de retour 0 et « Aucun redémarrage ». Utiliser un nouveau nom de fichier à chaque essai : le script refuse d'écraser une preuve existante.

## Couper Lockin pendant une mission de recette

1. Préparer une base de données distincte et un serveur distinct. Ne pas réutiliser le port 8770 ni la base de la session habituelle. Les variables du fournisseur et le jeton restent côté serveur ; ne pas les mettre dans les arguments de commande ni les journaux.
2. Dans un terminal où l'environnement du projet est activé et les variables requises sont déjà configurées, lancer :

```bash
LOCKIN_DB_PATH=/tmp/lockin-palier4-recette-1.db python scripts/palier4_fault.py --log /tmp/lockin-coupure-recette-1.jsonl -- python -m uvicorn app.main:app --host 127.0.0.1 --port 8774
```

3. Attendre que le serveur soit prêt. Ouvrir `http://127.0.0.1:8774/`, s'authentifier et lancer une mission. Noter son identifiant et le chemin du journal externe. Avec un fournisseur de test, afficher clairement « fournisseur simulé » ; ne pas présenter ses choix comme une décision de Haiku.
4. Pendant qu'une action est en cours, taper **`couper`** puis Entrée dans le terminal du superviseur. Montrer les deux événements externes et leur intervalle. La commande n'accepte aucun PID externe et ne signale que l'enfant qu'elle a elle-même créé. Ne pas employer de shell intermédiaire, `--reload`, plusieurs workers ni de lanceur qui détache un autre processus : la portée est l'enfant direct.
5. Montrer l'interface : les dernières données restent visibles ; la déconnexion n'est pas une preuve que la mission continue ou s'est arrêtée proprement. L'état reste à confirmer jusqu'au retour du serveur. La date locale d'une déconnexion du navigateur est une observation du navigateur.
6. Le superviseur **ne redémarre jamais** le serveur. Après avoir montré les preuves, relancer manuellement le même serveur, avec la **même base de recette**, pour tester la récupération :

```bash
LOCKIN_DB_PATH=/tmp/lockin-palier4-recette-1.db python -m uvicorn app.main:app --host 127.0.0.1 --port 8774
```

7. Retrouver la même mission dans l'interface. Examiner `recovery_detected` : son `at` est la détection **au redémarrage**, `last_seen_at` le dernier signe de vie connu avant l'interruption, et `interrupted_at: null` évite d'inventer une heure de mort. Le heartbeat serveur prévu toutes les deux secondes réduit la plage sans observation, sans déterminer une heure physique exacte. Rapprocher mission ID, base de recette, PID du processus de test et session du journal externe. Vérifier qu'aucune mission ni action n'a été relancée automatiquement.

Si le contrat moteur évolue, utiliser les noms du journal réellement reçu ; ne pas transformer une absence de `recovery_detected` en réussite. Conserver ensemble l'export de mission et le JSONL externe. La preuve de l'arrêt propre par le bouton est une recette distincte : `stop_requested`, annulation/fin de l'appel en cours, puis état terminal, sans tuer le serveur.

Chaque `operation_started` doit pouvoir être rapproché de son `operation_finished` grâce à `operation_id`. Le champ `outcome` distingue `success`, `error`, `cancelled` et `unknown` : après un kill brutal, une opération dont le résultat n'a pas été enregistré reste inconnue. `unknown` ne veut dire ni réussite ni échec certain chez le fournisseur distant. Les incidents du stockage peuvent être consultés par l'endpoint authentifié `/api/incidents`, dont le témoin reste indépendant du journal de mission lorsque cette base est indisponible.

## Autres ressources et limites

Une indisponibilité réseau, une clé révoquée ou un fichier inaccessible doit produire un incident dont le type et la réaction sont lisibles dans le journal. Il faut observer ce qui est effectivement détecté : retirer une clé du fichier `.env` après le démarrage ne révoque pas une clé déjà chargée en mémoire. Le dispositif présent instrumente uniquement une coupure de processus ; il ne prétend pas dater une panne réseau ou une révocation qu'il n'a pas effectuée.

Si le disque du journal devient inaccessible, aucun système qui écrit uniquement sur ce disque ne peut promettre une preuve durable à cet endroit. Le superviseur signale explicitement l'échec sur stderr et le code de sortie n'est pas un succès. Pour tester ce cas, le témoin externe doit écrire sur une ressource encore disponible.

## Codes de sortie du superviseur

| Code | Signification |
| --- | --- |
| 0 | SIGKILL confirmé sur l'enfant, preuve externe écrite, aucun redémarrage |
| 2 | Arguments invalides ou plateforme non prise en charge |
| 3 | Recette annulée, entrée fermée ou enfant sorti avant la coupure |
| 4 | Coupure échouée ou non confirmée comme SIGKILL |
| 70 | Échec du lancement de l'enfant |
| 74 | Journal externe indisponible ou écriture de preuve échouée |

`quitter`, fin d'entrée et Ctrl+C annulent la recette et nettoient l'enfant du superviseur. Ces sorties n'écrivent pas un faux `fault_applied`.
