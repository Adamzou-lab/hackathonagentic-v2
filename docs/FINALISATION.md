# Finalisation après v1.0

Cette correction est postérieure au gel : le tag v1.0 reste inchangé.

## Comportement

- Le budget total inclut une réserve de sauvegarde : 2 actions sur 10 en Rapide,
  3 sur 20 en Standard et 3 sur 100 en Approfondi. Les petits budgets conservent
  au moins une action de lecture (trois en mode automatique pour découvrir,
  sélectionner et lire). Avec moins de 4 actions en automatique, une sauvegarde
  n'est pas garantie ; l'interface le signale.
- Le serveur entre en finalisation à la réserve d'actions, à 70 % du seuil de
  tokens ou à vingt secondes de l'échéance. Cette phase interdit les nouveaux
  outils de recherche/lecture et conserve uniquement sauvegarde, fin ou refus.
- Une sauvegarde réussie en finalisation clôt la mission immédiatement, sans
  appel supplémentaire au modèle pour formater la synthèse. Elle reste signalée
  comme partielle. Deux constats sauvegardés terminent une veille Rapide normale.
- Le format d'outil proposé au modèle ne contient que source_id et passage_id.
  Le serveur résout la citation exacte ; l'ancien format quote reste accepté
  côté serveur pour compatibilité. Le XOR du validateur Pydantic n'apparaissait
  pas dans son JSON Schema : cela provoquait des propositions invalides répétées.
- Les erreurs de validation donnent au modèle les champs et codes fautifs,
  sans recopier les entrées ni des données confidentielles.

## Coût

Le pack Rapide autorise une recherche web facturable au maximum, découverte
automatique comprise ; Standard en autorise deux, Approfondi quatre. Les liens
déjà découverts restent disponibles pour lecture. Les tentatives réservées
comptent même si le fournisseur échoue.

Les seuils de tokens manuels sont 16 000 / 24 000 / 40 000. Le mode automatique
ajoute 16 000 pour la découverte native, dont un essai a consommé près de
14 000 tokens avant toute lecture. Ces seuils sont vérifiés entre les appels :
le dernier peut les dépasser et un appel interrompu peut avoir un coût inconnu.
Une réserve d'actions ne garantit ni la disponibilité du fournisseur ni celle
des pages, ni un constat lorsque les preuves sont insuffisantes.

Le contexte conserve six passages de chacune des deux dernières pages, deux
résultats d'outils et les URL disponibles. Les résultats de découverte complets
ne sont pas répétés après la sélection des domaines.

## Validation

354 tests Python réussis, tests frontend réussis, évaluation 10/10. Tests ajoutés :
finalisation sur actions/tokens/temps, refus serveur d'une lecture pendant cette
phase, impossibilité d'un second appel web en Rapide et format de preuve unique.
Les tests de délai isolent l'annulation d'un appel déjà engagé de la nouvelle
entrée anticipée en finalisation.

Les essais réels ont révélé deux échecs avant correction : un seuil automatique
trop bas, puis des preuves mal formées faute de schéma exclusif. Après correction
du schéma, la finalisation seule sur des pages réellement collectées a sauvegardé
un constat en 6 secondes et 5 620 tokens, sans nouvelle recherche web. Cette mesure
exclut le coût des recherches précédentes ; elle n'est pas un coût de veille complète.

Le dernier essai complet automatique, après correction, a conservé deux constats
en 28 secondes, 6 actions et 29 839 tokens (une seule recherche web facturable).
Le statut reste budget_exhausted parce que la finalisation a été déclenchée par
le seuil de tokens ; la synthèse partielle est présente. Il s'agit d'un essai,
pas d'une garantie de coût ou de qualité pour tous les sujets.

Quand une synthèse existe avant l'échéance, une courte animation annonce le temps
gagné. Aucun temps d'attente artificiel n'est ajouté. Une synthèse partielle est
explicitement nommée ; les erreurs et les recherches vides ne sont pas célébrées.
L'animation respecte la préférence de réduction des mouvements.


## Optimisation suivante — 9 septembre 2026

Le plafond total de tokens ne change pas. La réserve de finalisation est désormais
calculée à partir des trois dernières décisions mesurées : maximum de leur taille,
multiplié par 1,5, plus 4 096 tokens, avec un minimum de 8 192. Elle couvre la
proposition finale et sa vérification sémantique. Sans décision mesurée,
la réserve historique de 30 % est conservée. Le contenu des recherches web natives
n'entre pas dans cette estimation d'une décision. La réserve exacte figure dans
`finalization_started`. Ce calcul reste une estimation ; le contrôle entre appels
n'est pas une limite stricte de facturation côté fournisseur.

Les liens déjà trouvés sont conservés, y compris après la sortie de l'historique
court. Tant que des liens non lus et sans échec connu sont disponibles, le modèle
choisit entre lecture, sauvegarde, fin ou refus, sans nouvelle recherche web payante.
Le choix de l'action reste effectué par le modèle, sans routage par mots-clés.
Avant toute lecture, le schéma de sauvegarde inutile n'est pas envoyé. Les étapes
de découverte/sélection reçoivent leurs consignes spécifiques et un contexte réduit.
La recherche native est invitée à ne pas rédiger une synthèse qui serait ignorée.

Le catalogue est limité à quatre extraits par page au lieu de six, sur deux pages.
Le classement lexical local sert uniquement à sélectionner des données ; il ne
choisit aucun outil. Les extraits gardent leur texte et identifiant exacts, contrôlés
sur la page lue. Sans correspondance lexicale, ils sont répartis dans le document.
Cette sélection partielle ne garantit pas la couverture complète de chaque page.

Le format imbriqué de `save_finding` est montré explicitement. Une relance après
échec de finalisation est évitée si le reliquat ne couvre pas une décision estimée.
Les résultats déjà sauvegardés restent disponibles et partiels, les erreurs restent
journalisées. L'interface distingue limite de consommation, d'étapes et de temps.

Validation : 371 tests Python, 14 tests frontend, évaluation automatique 10/10.
Ces réductions de contexte ne garantissent pas un prix par sujet ni une durée de
10 minutes : celle-ci reste un maximum, indépendant des plafonds de consommation.


Une recherche native supplémentaire est masquée au modèle et bloquée côté serveur
si le reliquat ne couvre pas 1,5 fois le plus gros appel web natif mesuré (minimum
12 000 tokens) plus la réserve de finalisation. La première recherche reste autorisée,
faute de mesure préalable. C'est une estimation prudente, pas une borne du fournisseur.
Le blocage serveur est journalisé `web_search_skipped` ; une sauvegarde reste possible.

Les deux essais réels avant ce dernier contrôle n'ont pas démontré de réduction du
coût total : le premier a conservé un constat en 43 113 tokens, le second a atteint
55 005 tokens sans constat validé. Ce second essai a révélé un appel web natif de
18 177 tokens, lancé alors que 36 828 tokens sur 40 000 étaient déjà consommés.
Le test automatisé de non-régression vérifie que ce type d'appel n'est plus envoyé.
Aucun troisième essai payant n'a été lancé ; le gain réel global reste à mesurer
sur un ensemble comparable de sujets. Ne pas annoncer un pourcentage d'économie.

## Fiabilité des constats et reprise économique — 9 septembre 2026

Avant toute écriture, un second appel court vérifie que les affirmations du constat
sont bien soutenues par les extraits exacts. Une approbation produit l'événement
`finding_verified`, puis seulement `finding_saved`. Un rejet produit
`finding_rejected` et `unsupported_claim` ; aucun constat n'est alors publié.
Cette vérification est comptée dans les appels, les tokens et le coût affiché.
Un contrôle réel volontairement contradictoire avec `claude-haiku-4-5` a bien été
rejeté (`contradicted`) : 1 014 tokens d'entrée, 30 de sortie, aucun appel web,
coût estimé 0,001164 $US.

Une demande strictement identique réutilise gratuitement pendant 24 heures une
veille terminée ou une veille partielle contenant déjà au moins un constat. Le
motif `recent_partial` est affiché. Le bouton « Compléter cette veille » crée une
nouvelle exécution et, pendant six heures, reprend jusqu'à deux pages déjà lues et
les sources sélectionnées : ces lectures ne sont ni répétées ni refacturées.

Le lecteur accepte désormais HTML, RSS et Atom, extrait davantage de dates de
publication et suit jusqu'à trois redirections seulement après nouvelle validation
HTTPS, domaine, DNS public et robots.txt de chaque destination.
