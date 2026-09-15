# QA — Packs illustrés et centrage du titre Lockin, 14 septembre 2026

final result: passed

## Référence et captures

- Vérité visuelle : `design/loupe/packs-reference.png`, 1173 × 1341 px, maquette validée par Adam. Trois lignes représentent trois états successifs du même composant.
- Implémentation : http://127.0.0.1:8782/?demo, navigateur intégré Codex.
- Captures d’implémentation : images inline dans cette conversation ; le navigateur ne fournit pas de chemin de fichier. Aucun chemin local de capture n’est inventé.
- Comparaison finale : référence et capture ordinateur de l’état Approfondi ouvertes ensemble dans le même résultat d’outil. Les états Rapide et Standard ont également été inspectés.
- Viewport ordinateur : 913 × 767 CSS px, capture affichée 913 × 767 px. Mobile : 390 × 844 puis 320 × 844 ; réglage restauré ensuite.
- Normalisation : comparaison du sélecteur uniquement, et non de la planche entière avec l’application. La ligne source occupe environ 1095 px de large ; le sélecteur réel 734 px (facteur visuel ≈ 0,67). Les états et le thème sombre sont identiques. Pas de précision pixel à pixel revendiquée entre un mock raster et des contrôles natifs.
- Preuve ciblée : les trois cartes de l’application sont entièrement lisibles dans les captures du viewport, avec mesure DOM des dimensions. Une tentative de capture découpée du navigateur a renvoyé une mauvaise région ; elle est exclue de la comparaison. Les captures complètes correctes permettent l’inspection du composant sans ce découpage.

## Corrections et historique

1. [P2 corrigé] Mascotte initialement trop petite (slot 112 px dans une carte de 184 px). Slot porté à 176 px sur ordinateur, avec ratio conservé, puis contrôlé sur les trois poses et sur mobile. Le personnage occupe maintenant presque toute la hauteur utile.
2. [P2 corrigé] Titre et bloc texte sous-dimensionnés. Largeur maximale du formulaire augmentée, titres sélectionnés entre 23 et 28 px, descriptions entre 12 et 14 px ; texte centré verticalement face à l’image. Les captures finales montrent le nom Approfondi en entier, sans recouvrement.
3. [P2 corrigé] Ouverture de la personnalisation sans désélection. État personnalisé explicite ajouté : radios décochés, images masquées, cartes de 116 px de haut. Les valeurs 20 actions / 10 minutes saisies manuellement restent personnalisées. Choisir Approfondi remet bien 100 actions / 30 minutes et ferme les réglages.
4. Demande d’Adam appliquée : sprites des packs déplacés davantage vers la gauche, avec espace de texte recalculé (retrait droit de 34 px sur ordinateur, 14 px à 360 px et moins).
5. [P2 corrigé] Le groupe titre + mascotte était centré, décalant le titre de 52,74 px vers la gauche. La grille réserve maintenant deux colonnes latérales égales ; le titre seul est centré, avec l’écart de 30 px choisi par Adam conservé. À 700 px et moins, la mascotte passe sous le titre pour préserver la lisibilité.

Aucun P0/P1/P2 restant dans le périmètre.

## Cinq surfaces de fidélité

- Typographie : famille Inter et polices de repli du site conservées ; titres 600, corps 400. Nom, descriptif et durée hiérarchisés. Ajustement de taille au conteneur ; Approfondi reste lisible à 320 px.
- Espacement : cartes ordinateur 367 × 184 px sélectionnée / 175 × 116 px non sélectionnées au viewport contrôlé ; alignement vertical central, intervalles de 8 px. À 390 px : cartes de 320 px de large, hauteurs 176 / 104 px. Pas de débordement horizontal constaté.
- Couleurs : tokens clair/sombre existants, bordure terracotta et fond légèrement teinté pour la sélection. Radios natifs suivent le thème. Le thème clair est pris en charge par les tokens, mais n’a pas été forcé pendant cette vérification.
- Images : trois vrais WebP transparents réutilisés dans les packs, sans déformation ; une image visible uniquement dans le pack choisi. Deux poses supplémentaires sont intégrées : clin d’œil près du titre d’accueil et lecture assise près du titre de mission. Les dessins d’origine restent disponibles hors frontend. La présente correction visuelle porte sur le centrage du titre d’accueil.
- Contenu : textes conformes aux packs retenus, mêmes limites et budget effectif qu’avant. Les légendes de la planche de présentation ne sont pas ajoutées au produit.

## Vérifications

- Sélection Rapide / Standard / Approfondi dans le navigateur ; un seul radio et un seul sprite actifs.
- Navigation clavier par flèche Standard → Approfondi contrôlée.
- Personnalisation : zéro radio actif, trois images d’opacité 0, trois cartes compactes ; retour à un pack fonctionnel.
- Parcours démo complet : sélection Rapide → lancement → synthèse fictive terminée en cinq secondes, aucun appel API réel.
- Aucun message console error pendant le contrôle final.
- 14 tests frontend existants réussis ; syntaxe JavaScript et `git diff --check` réussis. Pas de nouveaux tests miroirs de styles.
- Animation : expansion 380 ms, hauteur 320 ms, image en fondu ; masquage au retrait de sélection. `prefers-reduced-motion` neutralise les transitions via la règle existante. Réglage OS non modifié : vérification de cette préférence par lecture du CSS, pas par bascule système.
- Centrage du titre : capture fournie par Adam comparée au rendu corrigé dans le navigateur. Mesure DOM à 1470 px : centre page = centre titre = 735 px, écart titre/mascotte = 30 px. Capture mobile 390 × 844 inspectée : titre et mascotte centrés, aucun chevauchement. Mesures complémentaires à 701 et 320 px : titre au centre exact, aucun débordement horizontal. Viewport rétabli après contrôle.
- Aperçu de développement : `scripts/preview_frontend.py` sert directement `app/static` ; les sauvegardes CSS sont appliquées sans rechargement de page. Aucun appel au modèle pendant ces vérifications.

## Livraison

Aperçu local uniquement, aucune publication Vercel effectuée. Référence et images dans `design/loupe/` ; les cinq sprites utilisés figurent dans `app/static/assets/`.
