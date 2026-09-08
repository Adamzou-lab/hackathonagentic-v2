# Frontend Lockin — palier 3

L'interface reprend la maquette Lockin : palette corail, packs Rapide (10 actions / 5 min), Standard (20 / 10), Approfondi (100 / 30), curseurs synchronisés, jauges d'actions et de durée. Les données du mode normal viennent exclusivement des routes authentifiées décrites dans API.md.

## Lancement et modes

- `python3 start.py` : serveur normal. Le formulaire demande le jeton opérateur Lockin ; la clé Anthropic reste côté serveur. Aucun appel au fournisseur avant lancement explicite d'une mission.
- `python3 start.py --demo` : ouvrir l'URL avec `?demo`. Transport de démonstration local, sans appels API, bandeau explicite. Choisir succès, outil désactivé ou panne de lecture. Ces scénarios prouvent le rendu, pas un comportement du modèle.
- Pour une panne réelle reproductible, suivre RECETTE_PALIER3.md et son serveur de recette. Les décisions du modèle dans ce dernier sont réelles et payantes.

## Journal et cycle de mission

Chaque action montre son outil et son numéro, ses arguments validés et son résultat JSON dépliable. Les refus, échecs et interruptions ont des libellés distincts. Export du journal JSON, avec identifiant de mission et marqueur du mode simulé, sans jeton opérateur.

Les événements déjà reçus sont conservés par numéro de séquence pour ne pas fermer les détails ouverts à chaque actualisation. Le suivi évite le chevauchement des requêtes et ignore les réponses d'une ancienne génération. Une panne réseau laisse les dernières données visibles et propose de reconnecter le suivi ; l'identifiant de mission reste dans sessionStorage, le jeton reste en mémoire uniquement. Aucun deuxième lancement automatique n'est tenté après un POST en échec.

Le bouton Nouvelle veille est indisponible tant que la mission est active. Arrêt en cours et arrêt confirmé sont distincts. Les constats persistés restent disponibles après panne ou arrêt. Sources, preuves et textes sont rendus via textContent ; seuls des liens HTTPS sans identifiants sont cliquables.

## Vérifications effectuées le 8 septembre 2026

- 34 tests Python du backend réussis, sans API.
- 5 tests Node : `node --test tests/frontend_demo.test.cjs` (succès, refus, panne, budget et arrêt du simulateur).
- Syntaxe JavaScript et `git diff --check`.
- Navigateur : pack Rapide, mission simulée avec constat et extraits, journal détaillé ; serveur FastAPI avec fournisseur de test pour lancement authentifié, refus `tool_disabled_for_test` et arrêt confirmé. Aucun appel Anthropic pour ces vérifications frontend.
- Texte `<img src=x onerror=alert(1)>` rendu littéralement, aucun élément image créé dans le titre de mission.
- Contrôle mobile à 390 px : largeur du document et du contenu à 390 px, sans débordement horizontal.

## Dépendance streaming

Le contrat streaming de Claude n'était pas livré lors de cette intégration. Le client utilise donc le GET d'instantané existant toutes les secondes et l'indique à l'écran. Ce lot ne revendique pas le bonus streaming.

À réception du contrat, remplacer le suivi périodique par le flux authentifié documenté, corréler les événements par mission/action/séquence, gérer reconnexion et arrêt du lecteur, et présenter les deltas de réponse réels. Ne pas inventer une route ou un format SSE avant l'accord avec Claude. Les fichiers backend, provider et API.md sont restés hors de ce lot.
