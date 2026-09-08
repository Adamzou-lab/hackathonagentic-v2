# SPEC : Le Métronome

Palier 1, cadrage. Binôme Adam et Panaki.

## Le problème en 5 lignes

Un développeur qui veut suivre les outils de création d'agents IA doit ouvrir une dizaine de sources officielles et trier lui-même ce qui est nouveau.
Le travail est long, répétitif, et il est refait presque à l'identique chaque semaine.
Nous confions cette collecte à un agent qui travaille seul pendant une durée bornée, sans validation humaine à chaque étape.
L'agent doit rendre un résultat exploitable même si on l'interrompt avant la fin, et rester capable de dire précisément ce qu'il a déjà fait.
Le sujet de veille est un paramètre : la démonstration porte sur l'IA agentique, mais le système doit accepter n'importe quel autre sujet.

## Mission de démonstration

Identifier les nouveautés des sept derniers jours sur les frameworks et outils de création d'agents IA, à partir de domaines fournis au lancement ou découverts automatiquement, puis produire une synthèse dédupliquée où chaque entrée porte un lien, une date et l'intérêt pratique pour un développeur.

Trois règles tenues par le système, pas par le sujet choisi :

- La date de publication et la date de consultation sont deux champs distincts. Une date introuvable est marquée inconnue, jamais devinée.
- « Aucune nouveauté pertinente trouvée » est un résultat valide. L'agent n'a pas le droit d'inventer de l'actualité pour remplir le rapport.
- Aucun résultat n'est écrit en dur. Le jury doit pouvoir relancer sur un autre sujet et d'autres sources sans que nous touchions au code.

## User stories

**US1.** En tant qu'utilisateur, je donne un sujet, un budget et le mode de sélection des sources, je lance l'agent, puis je ferme la page. Il continue sans moi.

**US2.** En tant qu'utilisateur, je peux arrêter l'agent à n'importe quel moment et récupérer aussitôt ce qu'il a déjà trouvé, avec les sources correspondantes.

**US3.** En tant qu'utilisateur, je lis le journal et je reconstitue exactement où en était l'agent à un instant donné : quelle action, quel budget restant, quelles sources déjà retenues.

## Hors-scope

Cette section est plus longue que le scope, volontairement. Chaque exclusion est un choix, pas un oubli.

**1. Aucune mémoire opaque ou illimitée.**
Les veilles sont désormais des fiches durables, enrichies par des exécutions séparées.
Chaque actualisation reçoit au maximum 20 résumés factuels et 12 000 caractères de
contexte, avec les identifiants des constats et de la mission d'origine. Ce contexte
est conservé dans le snapshot et marqué non fiable. Les anciennes preuves et les
journaux ne sont jamais réécrits. Les rapprochements de sujets seulement similaires
nécessitent un choix explicite de l'opérateur.

**2. Pas de comptes connectés ni de sources authentifiées.**
L'agent ne lit que du web public. Le jury doit pouvoir rejouer la démonstration sans nos identifiants. Et un identifiant stocké dans le projet devient une cible le vendredi, pendant la chasse ouverte.

**3. Aucun contournement des restrictions d'un site.**
Nous respectons `robots.txt` et les limites de débit. Un agent qui force l'accès rapporte des données que nous ne pourrions pas défendre à l'oral. Ce sujet note la traçabilité de la collecte, pas son volume.

**4. Aucune publication automatique, aucune écriture vers l'extérieur.**
L'agent écrit son rapport dans notre base, et nulle part ailleurs. Pas d'envoi de courriel, pas de publication, aucune écriture sur un service tiers. Il émet bien des appels sortants pour collecter, puisque c'est son métier : recherche, lecture de pages, appel au modèle. La frontière que nous posons est entre lire et écrire, pas entre appeler et ne pas appeler. Un agent autonome qui publie seul transforme une erreur de collecte en erreur publique, et nous ne serions pas là pour l'arrêter.

**5. Pas de navigation libre après sélection des sources.**
En mode manuel, l'opérateur donne de un à cinq domaines. En mode automatique, le
modèle découvre des candidats via une recherche web, puis sélectionne jusqu'à cinq
domaines parmi ces seuls résultats, avec un motif visible. Le serveur vérifie cette
sélection et leur résolution DNS publique. Les lectures ultérieures restent limitées
à ces domaines, avec nouvelle vérification DNS à chaque connexion. Le modèle ne peut
pas ajouter un domaine arbitraire au fil de la lecture.

**6. Pas de multi-agents.**
Une seule boucle, un seul agent. Ajouter des sous-agents multiplie les endroits où une panne peut passer inaperçue, ce qui est précisément le risque que ce sujet sanctionne.

**7. Pas de PDF ni d'images.**
Nous restons sur du HTML textuel. L'OCR ajouterait un mode de panne qui n'a aucun rapport avec l'autonomie que nous devons démontrer.

**8. Pas de gestion multi-utilisateur.**
Un seul opérateur local, pas de comptes, pas de rôles. Le sujet évalue l'autonomie d'un agent, pas un système de permissions.

**9. Priorité aux sources primaires, sans certification automatique.**
La découverte privilégie les sites officiels et les publications d'origine, leur
pertinence et leur compétence sur le sujet. Nous ne prétendons pas prouver que les
cinq domaines choisis sont « les plus fiables ». Moins de cinq sources est acceptable.
Les domaines et motifs sont visibles et peuvent être modifiés pour une actualisation.
Les informations sans date vérifiable restent marquées inconnues ; une correction
est liée au constat précédent et conserve l'accès aux versions anciennes.

**10. Pas de garantie de vérité, ni de classement objectif.**
L'agent résume bien l'intérêt pratique d'une nouveauté pour un développeur : c'est la mission, et nous ne l'excluons pas. Ce qu'il ne fait pas, c'est garantir que l'information est vraie, ni présenter son appréciation comme un classement objectif. Ce qu'il écrit est une lecture, donnée comme telle et rattachée à sa source, pour que le lecteur puisse trancher lui-même. Nous n'ajoutons pas non plus un second modèle chargé de noter le premier : cela déplacerait le problème de confiance d'un cran sans le résoudre, puisqu'il faudrait alors justifier pourquoi on croit le juge.

**11. Pas de journalisation du raisonnement interne du modèle.**
Le journal enregistre les actions, leurs paramètres, leurs résultats et une justification courte. Il n'enregistre pas la réflexion complète du modèle. Ce raisonnement n'est pas une preuve : ce qui prouve ce qu'a fait l'agent, c'est l'appel d'outil réellement parti et ce qui en est revenu. Le stocker ferait grossir le journal sans rendre l'exécution plus reconstituable.

### Le non argumenté proposé pour la carte bonus

L'exclusion numéro 1 : pas de mémoire opaque. Chaque apport de contexte est borné, versionné et rattaché à des preuves consultables.

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
