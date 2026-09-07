# SPEC : Le Métronome

Palier 1, cadrage. Binôme Adam et Panaki.

## Le problème en 5 lignes

Un développeur qui veut suivre les outils de création d'agents IA doit ouvrir une dizaine de sources officielles et trier lui-même ce qui est nouveau.
Le travail est long, répétitif, et il est refait presque à l'identique chaque semaine.
Nous confions cette collecte à un agent qui travaille seul pendant une durée bornée, sans validation humaine à chaque étape.
L'agent doit rendre un résultat exploitable même si on l'interrompt avant la fin, et rester capable de dire précisément ce qu'il a déjà fait.
Le sujet de veille est un paramètre : la démonstration porte sur l'IA agentique, mais le système doit accepter n'importe quel autre sujet.

## Mission de démonstration

Identifier les nouveautés des sept derniers jours sur les frameworks et outils de création d'agents IA, à partir d'une liste de sources officielles fournie au lancement, puis produire une synthèse dédupliquée où chaque entrée porte un lien, une date et l'intérêt pratique pour un développeur.

Trois règles tenues par le système, pas par le sujet choisi :

- La date de publication et la date de consultation sont deux champs distincts. Une date introuvable est marquée inconnue, jamais devinée.
- « Aucune nouveauté pertinente trouvée » est un résultat valide. L'agent n'a pas le droit d'inventer de l'actualité pour remplir le rapport.
- Aucun résultat n'est écrit en dur. Le jury doit pouvoir relancer sur un autre sujet et d'autres sources sans que nous touchions au code.

## User stories

**US1.** En tant qu'utilisateur, je donne un sujet, une liste de domaines autorisés et un budget, je lance l'agent, puis je ferme la page. Il continue sans moi.

**US2.** En tant qu'utilisateur, je peux arrêter l'agent à n'importe quel moment et récupérer aussitôt ce qu'il a déjà trouvé, avec les sources correspondantes.

**US3.** En tant qu'utilisateur, je lis le journal et je reconstitue exactement où en était l'agent à un instant donné : quelle action, quel budget restant, quelles sources déjà retenues.

## Hors-scope

Cette section est plus longue que le scope, volontairement. Chaque exclusion est un choix, pas un oubli.

**1. Aucune mémoire d'une mission n'est réinjectée dans la suivante.**
C'est notre exclusion la plus importante, et elle demande une précision. Nous conservons les journaux et les rapports des missions passées : ce sont nos preuves, et nous ne les effaçons pas. Ce que nous refusons, c'est de les réinjecter comme contexte du modèle au lancement d'une nouvelle mission.
La raison n'est pas qu'une mémoire importée serait impossible à tracer : versionnée, elle le serait. C'est qu'elle rendrait chaque mission dépendante des précédentes, et qu'expliquer une décision demanderait alors de lire une autre exécution que celle qu'on examine. Nous préférons une mission qui se rejoue seule et un journal qui se suffit à lui-même.

**2. Pas de comptes connectés ni de sources authentifiées.**
L'agent ne lit que du web public. Le jury doit pouvoir rejouer la démonstration sans nos identifiants. Et un identifiant stocké dans le projet devient une cible le vendredi, pendant la chasse ouverte.

**3. Aucun contournement des restrictions d'un site.**
Nous respectons `robots.txt` et les limites de débit. Un agent qui force l'accès rapporte des données que nous ne pourrions pas défendre à l'oral. Ce sujet note la traçabilité de la collecte, pas son volume.

**4. Aucune publication automatique, aucune écriture vers l'extérieur.**
L'agent écrit son rapport dans notre base, et nulle part ailleurs. Pas d'envoi de courriel, pas de publication, aucune écriture sur un service tiers. Il émet bien des appels sortants pour collecter, puisque c'est son métier : recherche, lecture de pages, appel au modèle. La frontière que nous posons est entre lire et écrire, pas entre appeler et ne pas appeler. Un agent autonome qui publie seul transforme une erreur de collecte en erreur publique, et nous ne serions pas là pour l'arrêter.

**5. Pas de navigation libre.**
L'agent ne suit que des liens appartenant à la liste de domaines autorisée au lancement. Sans cette limite, une page peut l'emmener n'importe où et le budget se consomme en bruit.

**6. Pas de multi-agents.**
Une seule boucle, un seul agent. Ajouter des sous-agents multiplie les endroits où une panne peut passer inaperçue, ce qui est précisément le risque que ce sujet sanctionne.

**7. Pas de PDF ni d'images.**
Nous restons sur du HTML textuel. L'OCR ajouterait un mode de panne qui n'a aucun rapport avec l'autonomie que nous devons démontrer.

**8. Pas de gestion multi-utilisateur.**
Un seul opérateur local, pas de comptes, pas de rôles. Le sujet évalue l'autonomie d'un agent, pas un système de permissions.

**9. Pas de sources non officielles.**
Ni réseaux sociaux, ni agrégateurs, ni blogs tiers, même quand ils sont plus rapides que la source officielle. Deux raisons. La date affichée par un agrégateur est celle de la reprise, pas celle de l'annonce, et notre mission porte sur une fenêtre de sept jours : une date fausse rend le résultat faux. Ensuite, dix reprises d'une même annonce ne font pas dix confirmations, et notre agent n'a aucun moyen fiable de reconnaître qu'elles parlent de la même chose.

**10. Nous ne jugeons pas la qualité de ce que nous rapportons.**
L'agent garantit qu'une information vient bien de la source citée, à la date indiquée. Il ne dit pas si elle est importante, ni si elle est vraie. Nous n'ajoutons pas un second modèle chargé de noter le premier : ce serait déplacer le problème de confiance d'un cran, pas le résoudre, et il faudrait alors justifier pourquoi on croit le juge.

**11. Pas de journalisation du raisonnement interne du modèle.**
Le journal enregistre les actions, leurs paramètres, leurs résultats et une justification courte. Il n'enregistre pas la réflexion complète du modèle. Ce raisonnement n'est pas une preuve : ce qui prouve ce qu'a fait l'agent, c'est l'appel d'outil réellement parti et ce qui en est revenu. Le stocker ferait grossir le journal sans rendre l'exécution plus reconstituable.

### Le non argumenté proposé pour la carte bonus

L'exclusion numéro 1. Elle se défend en une phrase : nous gardons tous les journaux, mais nous n'en réinjectons aucun, pour qu'expliquer une exécution ne demande jamais d'en lire une autre.

## Critères de fin pour le MVP

Le MVP du palier 4 est atteint quand, sur un sujet que nous n'avons pas préparé :

1. la tâche démarre et tourne sans intervention,
2. on l'arrête en cours de route et l'arrêt est propre,
3. le journal permet de reconstituer l'état exact au moment de l'arrêt,
4. la synthèse partielle reste exploitable et chaque affirmation porte sa source.

## Liens

- Menaces : `MENACES.md`
- Outils et signatures : `OUTILS.md`
- Répartition du travail : `REPARTITION.md`
- Parcours, démonstration et recette : `PARCOURS.md`, `DEMO.md`, `RECETTE.md`
