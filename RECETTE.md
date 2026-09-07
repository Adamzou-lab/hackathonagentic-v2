# RECETTE.md — Le Métronome

Scénarios de test manuel, avec le résultat attendu à chaque fois. Les trois premiers couvrent les fins de mission subies, le quatrième la fin par échéance, le cinquième le cas où l'agent ne trouve rien.

Rappel utile pour lire ces scénarios : le budget compte des **tentatives d'outils** (recherche, lecture, sauvegarde, et chaque tentative en échec), pas des pages réussies. La durée maximale est une limite distincte du budget.

## Scénario 1 — Budget épuisé

**Mise en situation** : lancer une veille avec un budget volontairement bas (par exemple 5 tentatives) et une échéance large, sur un sujet qui offrirait normalement bien plus de sources à consulter.

**Résultat attendu** :
- L'agent s'arrête de lui-même dès que le budget atteint 0, sans intervention manuelle.
- Le statut passe à « arrêté (budget épuisé) », `budget_exhausted`, et non à « terminé ».
- La synthèse est présentée comme **partielle**, puisque la mission n'est pas allée à son terme.
- Les résultats obtenus jusque-là restent consultables intégralement : sources, synthèse, journal. Rien n'est perdu.
- Le journal montre que les tentatives en échec ont bien consommé du budget, elles aussi.

## Scénario 2 — Page inaccessible

Ce scénario doit tester une page **réellement jointe qui échoue**, pas une URL rejetée avant tout accès. Les deux cas existent et ne prouvent pas la même chose.

**Mise en situation** : inclure dans les domaines autorisés une page de test contrôlée qui répond en délai dépassé ou en erreur serveur, et laisser l'agent la sélectionner normalement. Prévoir suffisamment de budget pour que la mission continue après l'échec.

**Résultat attendu** :
- L'échec apparaît explicitement dans la liste des sources et dans le journal, jamais en silence.
- Le journal montre **deux tentatives au maximum** sur cette source, puis un abandon explicite. Rappeler la même source plus tard ne remet pas ce compteur à zéro.
- Chaque tentative en échec a consommé du budget, et cela se lit dans le journal.
- L'agent poursuit sur les autres sources tant que le budget et l'échéance le permettent.
- La synthèse ne s'appuie que sur les sources effectivement récupérées, et signale que des sources ont été abandonnées.

**Variante à tester séparément** : une URL hors des domaines autorisés, ou une adresse locale ou privée. Résultat attendu différent : refus **avant** toute requête, avec un motif explicite, et aucune tentative comptée comme accès à la source.

## Scénario 3 — Arrêt manuel

**Mise en situation** : lancer une veille avec un budget et une échéance confortables, puis cliquer sur « Arrêter l'agent » en cours d'exécution, si possible pendant qu'une lecture de page est en cours.

**Résultat attendu** :
- Dès que le serveur **reçoit** la demande, plus aucune nouvelle action n'est autorisée. La garantie porte sur la réception côté serveur, pas sur l'instant du clic.
- Le statut passe par « arrêt en cours » (`stopping`) tant qu'un appel déjà parti n'est pas terminé, puis par « arrêté » (`stopped`). Le passage par l'état intermédiaire doit être visible.
- Un résultat qui arriverait pendant l'arrêt est tracé dans le journal mais ne déclenche aucune action suivante.
- Après l'arrêt, l'état final reste affiché : temps écoulé, budget restant, sources consultées, sources abandonnées.
- La synthèse partielle et le journal concordent : le dernier événement du journal correspond à ce que montre l'écran d'état.

## Scénario 4 — Échéance atteinte

**Mise en situation** : lancer une veille avec une échéance courte (par exemple 3 minutes) et un budget large, de façon que le temps s'épuise avant les tentatives.

**Résultat attendu** :
- L'agent s'arrête à l'échéance sans intervention, et le statut passe à « arrêté (échéance) », `deadline_reached`, distinct de « budget épuisé ».
- Le budget restant est encore positif, ce qui prouve que ce sont bien deux limites indépendantes.
- La synthèse est marquée partielle, et le journal permet de retrouver la dernière action lancée avant l'échéance.
- Aucune attente artificielle n'a été ajoutée pour remplir la durée : le journal montre un travail réel jusqu'à l'arrêt.

## Scénario 5 — Aucun résultat exploitable

**Mise en situation** : lancer une veille sur un sujet très étroit, avec des domaines autorisés qui ne publient rien à ce sujet dans la fenêtre de sept jours.

**Résultat attendu** :
- La mission se termine normalement et affiche explicitement qu'aucune nouveauté pertinente n'a été trouvée.
- Aucun constat n'est inventé, aucune date n'est devinée pour remplir le rapport.
- Le journal montre que les recherches et les lectures ont bien eu lieu : l'absence de résultat est un constat, pas une panne.
- Le statut est un état de fin normal, pas `failed`.
