# RECETTE.md — Le Métronome

Trois scénarios de test manuel, avec le résultat attendu à chaque fois.

## Scénario 1 — Budget épuisé

**Mise en situation** : lancer une veille avec un budget volontairement bas (ex. 3 actions) sur un sujet qui offrirait normalement plus de sources à consulter.

**Résultat attendu** :
- L'agent s'arrête automatiquement dès que le budget atteint 0, sans intervention manuelle.
- Le statut passe à « arrêté (budget épuisé) ».
- Les résultats obtenus jusque-là (sources consultées, synthèse partielle, journal) restent consultables intégralement, rien n'est perdu.

## Scénario 2 — Page inaccessible

**Mise en situation** : inclure dans les domaines autorisés une source qui répond en erreur ou timeout (URL invalide, page supprimée, délai dépassé).

**Résultat attendu** :
- L'échec est visible explicitement dans la liste des sources consultées et dans le journal (statut « erreur », pas silencieux).
- L'agent poursuit sur les autres sources disponibles au lieu de s'arrêter net, tant que le budget le permet.
- La synthèse finale ne s'appuie que sur les sources effectivement récupérées.

## Scénario 3 — Arrêt manuel

**Mise en situation** : lancer une veille avec un budget confortable, puis cliquer sur « Arrêter l'agent » en cours d'exécution, avant l'épuisement du budget.

**Résultat attendu** :
- Aucune nouvelle action (consultation de page, requête) n'est lancée après le clic sur arrêt.
- Le statut passe à « arrêté (manuel) ».
- L'état au moment de l'arrêt (budget restant, sources consultées, synthèse partielle) reste consultable et cohérent avec le journal.
