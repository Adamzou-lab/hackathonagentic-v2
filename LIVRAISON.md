# Palier 6 — préparation du gel

État vérifié le 9 septembre 2026. Ce document prépare la livraison ; il ne vaut
ni preuve d'une répétition réalisée ni déclaration de gel définitif.

## Version candidate

- Code actuellement sur main : `7fc0988723dba098f490fc1159bfa5fce42ec3e2`.
- Netlify : même commit dans `https://lockin-demo.netlify.app/version.json`.
- Backend : `/opt/lockin/releases/7fc0988`, service actif, santé publique `ok`.
- API configurée et activée ; accès public volontaire pendant la démonstration.
- Tag `v1.0` absent lors de la vérification.
- `JOURNAL.md` absent du commit candidat ; rédaction confiée à Claude.

Attention : dev est à `63456246f6fb89f808a538c831d7dd5fdd809ab9` après la PR #17.
Cette intégration ajoute un coût estimé en dollars mais retire le contrôle du
seuil de tokens, agrandit à nouveau le contexte et retire les améliorations du
streaming. Vérification isolée : 342 tests Python réussis, 4 échoués sur le seuil
de tokens. Ne pas fusionner dev aveuglément dans la version candidate.
Le code en ligne n'a pas été changé pendant cette préparation.

## Avant de poser v1.0

1. Adam confirme la version candidate. Si le choix est la version actuelle de
   main, intégrer uniquement les documents de livraison, sans le code de la PR #17.
2. Relire JOURNAL.md : cinq entrées factuelles minimum ; statut du secret confirmé
   par Adam ; paragraphe de chasse ouverte si nécessaire, sans divulguer le secret.
3. Vérifier que la dette technique assumée indique un choix, sa raison et sa limite.
4. Publier les documents et déployer le commit final, puis vérifier l'alignement.
5. Poser le tag annoté v1.0 sur ce SHA exact et le pousser. Ne jamais déplacer ce tag.
6. Répéter sur cette version, arrêt strict à cinq minutes, puis lire tout le journal.
   Garder la preuve de répétition séparément du dépôt gelé pour ne pas avancer le
   commit jugé. Aucun changement de code après le gel.

## Répétition réelle — déroulé de cinq minutes

Avant le chrono : ouvrir le site public sans `?demo`, la console de tests dans le
bon dépôt et JOURNAL.md. Vérifier qu'aucune mission d'un autre utilisateur ne tourne.
Préparer un minuteur avec une alarme à 5:00. Les recherches réelles consomment du
crédit ; la réutilisation d'un résultat ne démontre pas un nouvel appel au modèle.

| Temps | Action et preuve à montrer |
| --- | --- |
| 0:00–0:25 | Présenter Lockin : veille documentaire publique, sources, limites, journal. Montrer le tag et le SHA notés avant le départ. |
| 0:25–1:40 | Lancer une veille Rapide avec une durée d'une minute, sujet fourni sur place. Si elle est réutilisée, annoncer le cache ; utiliser une actualisation explicite pour montrer une exécution réelle. Montrer l'outil proposé puis ses arguments et le résultat dans le journal. |
| 1:40–2:30 | Ouvrir les constats et leurs extraits. Expliquer date inconnue, source unique ou absence de constat sans inventer un succès. Montrer tokens, appels et durée ; le seuil est vérifié entre les appels, pas un plafond exact de facturation. |
| 2:30–3:20 | Si la mission tourne encore, demander son arrêt et attendre l'état terminal. Désactiver l'API avec le bouton, tenter une recherche : montrer le refus explicite sans nouvel appel payant. Réactiver ensuite. |
| 3:20–4:15 | Lancer `python eval.py` dans l'environnement installé. Montrer le score et nommer la limite : doubles déterministes, pas une preuve que Haiku ne se trompe jamais. |
| 4:15–4:50 | Montrer Mes veilles, un journal horodaté et une limite assumée : une citation exacte ne garantit pas une interprétation correcte. |
| 4:50–5:00 | Conclure par le résultat observé et les limites. À l'alarme, arrêter la présentation même si une étape manque. |

En cas de panne : montrer l'erreur et son horodatage ; ne pas réparer, redéployer
ou modifier le code pendant la démonstration. Ne pas présenter une réponse tardive
comme une action accomplie avant la coupure.

La lecture intégrale de JOURNAL.md suit la répétition. Si le jury impose aussi
cette lecture dans les cinq minutes, refaire le déroulé avec une place suffisante
pour sa durée mesurée ; ne pas sauter des paragraphes.

## Fiche de preuve à remplir après la répétition

À conserver hors du dépôt gelé, par exemple en capture ou compte rendu partagé.

- Date, participants et conditions : à renseigner.
- Tag et SHA réellement présentés : à renseigner.
- Début du chrono, fin et durée : à renseigner.
- Identifiant de mission réelle : à renseigner.
- Étapes montrées, erreurs observées, état de l'API après répétition : à renseigner.
- Arrêt à 5:00 respecté : à confirmer après exécution.
- JOURNAL.md lu entièrement à voix haute : à confirmer après exécution.

Au moment de la rédaction, cette répétition palier 6 n'a pas encore été réalisée.
