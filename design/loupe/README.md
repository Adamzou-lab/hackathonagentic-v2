# Sprites de la Loupe — packs de recherche

L’ancienne mascotte globale a été retirée. L’intégration retenue le 14 septembre 2026
comprend les cartes de packs, d’après `packs-reference.png` :

- Rapide : `loupe-search-right.webp`.
- Standard : `loupe-ready.webp`.
- Approfondi : `loupe-reading.webp`.
- Titre d’accueil : `loupe-wink.webp`, à droite du titre centré.
- Titre de mission : `loupe-seated-reading.webp`.

La sélection agrandit la carte et révèle son image avec un fondu. Les autres cartes
reprennent leur taille compacte. L’ouverture des réglages personnalisés désélectionne
les packs ; choisir un pack rétablit sa sélection et ferme les réglages.
Les contrôles sont des radios natifs accessibles au clavier. Sous 760 px, les cartes
sont empilées. Les mouvements réduits sont respectés. Les cinq WebP du frontend
totalisent 162 736 octets. Le logo et les autres animations du site sont conservés.

Les huit poses sont conservées dans `design/loupe/assets/` (PNG transparent et WebP)
et dans `lockin-loupe-sprites.zip`, pour réutilisation par Adam.
Les images d’origine restent dans `source/` et les planches dans `sprites-clair.png`
et `sprites-sombre.png`.

| Fichier | Pose |
|---|---|
| loupe-idle | Face, bras détendus |
| loupe-search-left | Recherche, trois quarts gauche |
| loupe-search-right | Recherche, trois quarts droite |
| loupe-reading | Lecture du carnet |
| loupe-ready | Présentation d’une fiche |
| loupe-paused | Geste interrogatif |
| loupe-wink | Clin d’œil |
| loupe-seated-reading | Assise avec un livre |

Les six poses initiales sont en 512 × 512, personnage dans un cadre de 448 px, pieds alignés à y = 480.
Les poses clin d’œil (262 × 472) et lecture assise (310 × 472) sont recadrées.
 Images générées avec image_gen, puis détourées
et optimisées localement avec l’autorisation d’Adam. Les sources sont conservées.

Préparation reproductible : `python scripts/prepare_loupe_sprites.py`.
Dépendances de design uniquement : Pillow, NumPy, SciPy. Les fichiers préparés sont
écrits dans `design/loupe/assets/`, sans modifier le frontend.
