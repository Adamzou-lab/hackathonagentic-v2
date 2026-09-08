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

- 43 tests Python du backend réussis, sans API.
- 8 tests Node : `node --test tests/frontend_*.test.cjs` (succès, refus, panne, budget, arrêt, trames SSE découpées et accents, fin de flux, JSON invalide).
- Syntaxe JavaScript et `git diff --check`.
- Navigateur : pack Rapide, mission simulée avec constat et extraits, journal détaillé ; serveur FastAPI avec fournisseur de test pour lancement authentifié, refus `tool_disabled_for_test` et arrêt confirmé. Aucun appel Anthropic pour ces vérifications frontend.
- Texte `<img src=x onerror=alert(1)>` rendu littéralement, aucun élément image créé dans le titre de mission.
- Contrôle mobile à 390 px : largeur du document et du contenu à 390 px, sans débordement horizontal.

## Streaming intégré

Le contrat de Claude a été livré pendant ce travail sur `p3-streaming` à `6cf4307`, puis intégré avec le frontend sur adam. Le client utilise `fetch` sur `/api/missions/{id}/stream` avec Authorization Bearer et Last-Event-ID. Les événements journal sont dédupliqués par séquence et les instantanés sont relus pour les compteurs et états. Les fragments draft sont affichés comme provisoires, jamais interprétés comme actions ou preuves ; les arguments partiels ne sont jamais exécutés par le frontend.

Le lecteur supporte les trames fragmentées, UTF-8 et CRLF, ignore les keepalive, borne les données provisoires et ferme la connexion après end. Après coupure, reconnexion avec le dernier journal disponible, sans POST de mission. Un serveur plus ancien sans route stream conserve le suivi par polling. Les abonnements précédents sont annulés lors du changement de mission ou de reconnexion.

Vérification navigateur sur le serveur SSE intégré avec fournisseur de test : connexion authentifiée, fragments visibles pendant la mission, refus tool_disabled_for_test dans le journal, puis fin du flux. Aucun nouvel essai Haiku payant effectué. Le bonus streaming n'est donc pas déclaré acquis : refaire la présentation avec le fournisseur réel après accord sur le crédit API. La limite de Claude demeure : le résultat du moteur de recherche Anthropic arrive d'un bloc, seuls les fragments de décision du modèle sont diffusés.

### Refus des demandes hors périmètre

Avant tout outil, le modèle doit choisir `accept_scope` ou `refuse` ; cette étape
ne dispose d'aucun outil de recherche. Le serveur interdit recherche, lecture,
sauvegarde et fin normale tant que le périmètre n'est pas accepté. La décision
est comptée comme un appel modèle et soumise aux mêmes limites de temps.

Le périmètre est la veille/recherche documentaire publique sur les domaines
sélectionnés. Les actions physiques, achats, envois, modifications de systèmes,
demandes de secrets et demandes mixtes contenant une action interdite sont
refusés. Une demande ambiguë nécessite une reformulation. Aucun routage par
mots-clés du sujet n'est utilisé. Le classifieur sémantique reste un modèle :
une mauvaise classification demeure possible et doit être évaluée avec Haiku.

L'état terminal `refused` expose `refusal_reason`, un message fixe choisi par le
serveur à partir d'un code autorisé (aucune explication libre du modèle affichée).
Le journal publie `mission_refused`, puis `finished` ; le SSE se termine par `end`.
Une réponse modèle sans action, multiple ou marquée tronquée refuse proprement.
Les pannes réseau restent des erreurs techniques distinctes du refus.

Tests sans API : blocage avant validation, décisions malformées, refus visible
par API/SSE, et parcours accepté jusqu'à la recherche. Ces doubles ne prouvent
pas la classification réelle de « prépare-moi un sandwich ». Aucun appel payant
supplémentaire ni mise à jour de la maquette Netlify dans cette modification.

### Mes veilles et actualisations

La bibliothèque authentifiée liste les fiches conservées en SQLite et donne accès
aux exécutions et preuves antérieures. Une actualisation explicite consomme du
crédit API, avec un contexte borné des informations connues. La réutilisation d'une
veille identique récente reste sans nouvel appel. Les sujets proches nécessitent
un choix visible avant rattachement. Les sources automatiques choisissent jusqu'à
cinq domaines candidats ; le mode manuel reste disponible.
