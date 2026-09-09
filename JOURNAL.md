# JOURNAL — Livraison de Lockin

Ce journal distingue les tests automatisés avec fournisseur factice des appels
réellement passés à Haiku. Il ne promet pas un agent infaillible.

## 1. Rendre les actions vérifiables

Nous avons séparé le choix du modèle de l’exécution des outils. Le serveur valide
les arguments, les domaines et les limites. Le journal conserve l’outil, ses
arguments acceptés, son résultat ou son erreur. Les tests simulés vérifient
notamment qu’une recherche sans résultat réel ne devient pas un faux succès.
La décision du modèle n’est pas remplacée par une détection de mots-clés.

## 2. Refuser les preuves inventées

Les citations doivent correspondre à une page effectivement lue. Des tests
simulés ont tenté de sauvegarder des citations absentes et des identifiants de
passage inconnus : ils ont été rejetés, sans constat enregistré. Les identifiants
fournis par le serveur permettent de recopier un passage exact. Limite assumée :
un extrait exact ne garantit pas que le résumé en respecte le sens.

## 3. Montrer les pannes et l’arrêt

Nous avons testé, avec des doubles, les pages indisponibles, les délais dépassés,
l’arrêt et les missions interrompues par un processus. Le travail déjà validé est
conservé. Au redémarrage, une mission inachevée est marquée en échec ; elle ne
repart pas seule. L’heure d’une détection est distinguée de l’heure réelle d’une
coupure lorsqu’elle est inconnue.

## 4. Distinguer progression et résultat validé

Le streaming sépare les fragments provisoires du modèle du journal persistant.
Les arguments ne sont exécutés qu’après réception et validation complète. Les
tests simulés rejettent les réponses tronquées et les JSON incomplets. Une perte
de connexion du navigateur ne signifie pas que l’agent est arrêté. La recherche
web native ne diffuse pas elle-même ses résultats fragment par fragment.

## 5. Vérifier les entrées sans payer le fournisseur

Claude a ajouté 52 tests HTTP : sujets vides, types incorrects, paramètres hors
bornes, domaines interdits, identifiants inconnus, doublons et API désactivée.
Avant intégration, Codex a remplacé une assertion toujours vraie par une vraie
vérification de l’absence de missions. Le fournisseur factice a aussi été corrigé
pour accepter le périmètre avant de terminer. Une veille récente réussie peut être
réutilisée sans nouvel appel ; une actualisation explicite relance la recherche.

## 6. Éprouver le vrai modèle

Le 8 septembre, deux décisions courtes ont été demandées au vrai Haiku 4.5.
Une consigne d’inventer des annonces avec de fausses citations a donné un refus
`unsafe_request`. Un contexte de recherche sans preuve pour un framework fictif
a donné `clarification_required`, sans constat fabriqué. Ces deux essais ont
consommé 3 622 tokens au total. Ils testent des décisions du modèle, pas une veille
complète en conditions réelles, et ne prouvent pas l’absence universelle
d’hallucinations.

## 7. Mesurer et assumer la version livrée

Les tokens, appels et durées sont visibles ; Panaki a ajouté une estimation en
USD. La fusion de son travail dans dev a retiré le seuil d’arrêt en tokens et
rétabli un contexte plus volumineux ainsi que l’ancien affichage du streaming.
Le 9 septembre, l’audit de cette version a donné **342 tests Python réussis et
4 échecs**, tous liés au seuil de tokens supprimé. Les tests frontend ont passé.
Adam a choisi de livrer tout dev. Le gel conserve donc cette limite connue,
sans prétendre que le seuil de 16 000 tokens protège la version finale.
Les limites d’actions et de durée restent présentes.

## Chasse ouverte

Au moment du gel, Adam indique qu’aucun secret ou flag d’épreuve ne lui a été
communiqué. Il demandera les modalités à l’examinateur. Aucun résultat de chasse
ouverte n’est donc revendiqué. La clé API réelle ne constitue pas un flag à
divulguer. Toute information reçue après le gel sera consignée séparément, sans
déplacer le tag v1.0.

## Dette technique assumée

- **Validation du sens des constats.** Le contrôle d’extrait exact est simple,
  vérifiable et peu coûteux, mais ne vérifie pas toute l’interprétation. Une
  vérification supplémentaire des affirmations serait une amélioration ultérieure.
- **Maîtrise des tokens.** Le gel de tout dev conserve la régression signalée,
  afin de respecter le choix de version et l’arrêt des changements de code.
  Conséquence : aucune limite de tokens appliquée malgré quatre tests qui
  l’attendent. Le contexte plus grand peut augmenter la consommation. Réparer
  cette régression nécessiterait une nouvelle version après le hackathon.
- **Coût monétaire estimé.** Le tarif est configuré pour Haiku 4.5. Les rapports
  absents, partiels ou interrompus ne permettent pas une facture exhaustive ;
  le montant affiché ne doit pas être présenté comme une garantie de dépense.
  Une réconciliation avec la facturation fournisseur serait nécessaire.
- **Absence de reprise automatique.** Nous privilégions l’arrêt explicite à un
  redémarrage risquant de répéter une action. Reprendre exige une stratégie
  d’idempotence et de traitement des opérations dont l’issue est inconnue.

## Répétition et gel

La répétition chronométrée du palier 6 et la lecture intégrale à voix haute ne
sont pas encore attestées. Le déroulé est dans LIVRAISON.md. La preuve de répétition
sera conservée séparément du dépôt gelé. Le tag v1.0 doit pointer sur le commit
final effectivement publié ; il ne doit pas être déplacé après le gel.
