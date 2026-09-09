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
