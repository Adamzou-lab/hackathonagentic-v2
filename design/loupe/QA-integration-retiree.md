> Archive : cette intégration a été retirée le 14 septembre 2026 à la demande d’Adam. Ce rapport décrit la vérification antérieure, pas l’interface actuelle.

# QA — Loupe et sprites, 14 septembre 2026

final result: passed

## Référence et preuves

- Concept choisi : `design/loupe/source/loupe-reference.png`, 1254 × 1254.
- Sources des six poses : `design/loupe/source/loupe-*.png` (1254 × 1254).
- Planches normalisées : `design/loupe/sprites-clair.png` et `sprites-sombre.png`, 1200 × 900.
- Aperçu navigateur : http://127.0.0.1:8782/sprites.html ; intégration : http://127.0.0.1:8782/?demo.
- Captures d'implémentation : captures inline du navigateur Codex dans cette conversation, galerie repos/lecture claire et sombre, accueil, succès et panne. Le navigateur n'a pas fourni de chemin de fichier pour ces captures ; aucun chemin n'est inventé.
- Viewports inspectés : 1117 × 767 puis 913 × 767 selon panneau ; mobile 390 × 844. Le réglage temporaire mobile est remis à zéro après vérification.
- Comparaison : le PNG source détouré et la capture d'intégration ont été ouverts ensemble dans le même résultat d'outil. Les six poses finalisées ont ensuite été comparées sur les deux planches claire/sombre à la galerie navigateur. Comparaison de composant : la référence ne définit pas une page complète.
- Normalisation : sprites RGBA 512 × 512 ; corps contenu dans 448 px et pieds alignés à y=480. `object-fit: contain` préserve leur ratio dans les zones d'interface ; pas de redessin SVG approximatif.

## Constats et corrections

1. Fonds en damier réellement opaques sur repos/lecture/pause : corrigés après autorisation explicite d'Adam par segmentation locale du fond neutre. Détourages inspectés sur les deux fonds. Alpha des six WebP vérifié entre 0 et 255.
2. Le thème initial de la galerie ne suivait pas le bouton clair/sombre (héritage `body`) : corrigé avec `color-scheme: inherit`, puis contrôlé dans le navigateur en clair et sombre.
3. Taille des fichiers : six WebP totalisent 185286 octets ; PNG transparents également disponibles. Pas de chargement de toutes les poses dans le parcours de veille, seulement au changement d'état.
4. Transitions : deux calques superposés, image décodée avant remplacement, fondu de 300 ms et léger déplacement. Les changements rapprochés sont regroupés ; un ancien chargement ne peut pas réafficher une pose de succès après une panne.
5. Accueil mobile : la règle `display: block` héritée de l’image unique a été remplacée par `display: grid` pour superposer les deux calques. Vérifié dans le navigateur à 390 px : mêmes coordonnées y=189 après une transition repos → erreur, aucune augmentation de largeur (scrollWidth=390).

Pas d'écart P0/P1/P2 restant dans le périmètre de ces ajouts.

## Cinq surfaces examinées

- Typographie : police et hiérarchie Lockin conservées ; titres/étiquettes de galerie lisibles à 390 px.
- Espacement : aucune superposition constatée entre illustration, timer, coût et boutons ; galerie passe de six à trois colonnes en mobile.
- Couleurs : terracotta/crème/charbon cohérents entre poses ; légères variations de teinte dues à la génération, non bloquantes. Les contours sombres sont plus discrets en thème sombre, mais visage, gants et semelles restent lisibles.
- Images : vraie transparence, sans légende ni damier, proportions conservées, pieds alignés, visages et accessoires lisibles. Les six dessins sont des poses distinctes, pas une animation image par image.
- Contenu : aucun nouveau fait de recherche inventé ; la pose de réussite est réservée aux missions terminées avec résultats non partiels. Les cas vide, panne, arrêt, limite et perte de connexion ne célèbrent pas un résultat.

## Vérifications fonctionnelles

- 21 tests frontend passent, dont sept contrôles du compagnon : états conservateurs, chargement tardif, changements rapides, image manquante, mises à jour identiques et perte de connexion.
- Syntaxe JavaScript et `git diff --check` passent.
- Sélection de pose et bascule clair/sombre testées dans la galerie ; toutes ses images chargées en 512 × 512.
- Démo exécutée sans API : `search-right` utilise le bon WebP, puis `ready` utilise le sprite résultat. Scénario panne contrôlé précédemment : arrêt de l'animation et affichage de l'erreur. Aucun message console de niveau error après le scénario de succès avec les six sprites.
- Mouvements limités dans le temps. La règle CSS `prefers-reduced-motion: reduce` désactive animations/transitions ; réglage OS non modifié pendant la vérification.
- Fondu : deux calques et positions de départ animées observés dans la galerie ; une seule pose reste visible à la fin. Web Animations respecte également `prefers-reduced-motion`, y compris si la préférence change pendant le fondu (lecture du code, réglage OS non modifié).
- Nouvelle vérification des parcours locaux après intégration : accueil → recherche → résultat, panne de lecture → pose interrogative, domaine invalide → erreur et pose interrogative sur l’accueil. Aucun message console error. Vérification mobile succès et panne à 390 × 844 ; viewport restauré ensuite.
- Bibliothèque et clé API de production non touchées ; aucun appel modèle réel.

## Livraison

- Aperçu local uniquement : ces modifications visuelles ne sont pas encore publiées sur Vercel.
- Pack : `design/loupe/lockin-loupe-sprites.zip`, PNG + WebP + README.
