# Répartition du travail — Adam et Panaki

Sujet : **Le Métronome**, agent de veille web autonome. Démonstration sur les nouveautés de l'IA agentique des sept derniers jours, à partir de sources officielles autorisées.

Répartition demandée par Adam : **70 % de l'effort pour Adam, assisté de Codex et Claude ; 30 % pour Panaki**. C'est une estimation de charge, pas un quota de lignes de code ni de fichiers. Adam et Panaki restent responsables de leurs livrables et doivent tous deux savoir expliquer le fonctionnement complet.

## Palier 1 : conception uniquement

| Responsable humain | Assistance / rédaction | Fichiers | Critère de fin |
| --- | --- | --- | --- |
| Adam | Claude | `SPEC.md` | Problème en exactement 5 lignes, au plus 3 user stories, hors-scope argumenté d'au moins 5 items et plus développé que le scope. |
| Adam | Claude | `MENACES.md` | Chaque acteur et canal est identifié ; mensonge possible, conséquence et protection sont expliqués. |
| Adam | Codex | `OUTILS.md` | Chaque outil a un nom, une signature complète, des types définis et un effet de bord explicite. Les contrôles du serveur sont distincts des choix du modèle. |
| Adam | Codex | `REPARTITION.md` | Responsabilités, dépendances, circuit de contribution et préparation de l'oral sont explicites. |
| Panaki | Relecture par Adam | `PARCOURS.md` | Maquette sans code : sujet, domaines autorisés, budget, lancement, progression, arrêt, synthèse et journal. |
| Panaki | Relecture par Adam | `DEMO.md` | Exactement 6 étapes, du choix du sujet à la synthèse partielle et à la reconstruction de l'état après arrêt. |
| Panaki | Relecture par Adam | `RECETTE.md` | Pour budget épuisé, page inaccessible et arrêt manuel : conditions, manipulation et résultat observable attendu. |

Les trois fichiers de Panaki doivent rester courts : ce sont des supports de cadrage, pas des fonctionnalités supplémentaires. Les propositions techniques sont harmonisées entre les documents avant le checkpoint. La stack n'est pas considérée comme validée par ce document.

## Répartition de charge sur l'ensemble du projet

| Responsable | Périmètre | Part de l'effort total |
| --- | --- | ---: |
| Adam, avec les agents | Architecture, boucle agentique, recherche et lecture des pages, budgets et durée | 30 % |
| Adam, avec les agents | Journal persistant, arrêt, gestion des erreurs, protections et tests de fiabilité | 30 % |
| Adam, avec les agents | Contrat API, intégration et déploiement | 10 % |
| Panaki | Interface simple de lancement, suivi, arrêt et consultation | 15 % |
| Panaki | Documentation de démarrage, scénario de démo et vérifications manuelles | 10 % |
| Panaki | Cas de vérification : exécution normale, panne de source, interruption | 5 % |
| **Total** | **Adam 70 % / Panaki 30 %** | **100 %** |

Pour faciliter le travail de Panaki, Adam fournit un contrat API stabilisé et des exemples de réponses ; les données fictives de développement ne remplacent pas une démonstration sur des sources réelles. Panaki décrit les résultats attendus, Adam implémente les tests techniques correspondants. La persistance et l'exécution longue restent côté serveur.

L'affectation future du code entre Codex et Claude sera précisée fichier par fichier au palier autorisant l'implémentation. La répartition de rédaction ci-dessus est celle du palier 1.

## Contributions et coordination

- `adam` : contributions pilotées par Adam, y compris celles de Codex et Claude ; `panaki` : contributions de Panaki.
- Pull requests vers `dev` pour intégrer et relire ; passage de `dev` vers `main` après validation. `main` doit rester démontrable.
- Codex et Claude utilisent des copies de travail isolées s'ils travaillent en parallèle. Ils ne changent pas la branche du clone utilisé par l'autre et ne poussent jamais en force pour résoudre une divergence.
- Chaque agent reste sur les fichiers attribués. Un changement de contrat est signalé à l'autre avant intégration ; pas de réécriture silencieuse de son document.
- La fiche partagée du hackathon dans le vault porte les décisions et les passations actuelles. Une note déposée n'est pas un accusé de réception ; chacun consulte les nouvelles décisions avant de commencer ou d'intégrer son travail.

## Validation humaine avant le checkpoint

1. Adam vérifie que SPEC, menaces et outils décrivent le même système ; Panaki vérifie que son parcours et sa démo correspondent aux comportements promis.
2. Chacun explique seul le modèle de menace complet, puis l'autre pose des questions : page qui ment, résultat de recherche piégé, appel bloqué, budget épuisé et arrêt pendant un appel.
3. Chacun doit savoir situer les décisions du modèle, les permissions du programme et les preuves conservées. Les explications ne se limitent pas aux fichiers de sa propre partie.
4. Corriger les incohérences puis présenter le palier ; aucune implémentation applicative avant sa validation.
