# Palier 6 — préparation du gel

État vérifié le 9 septembre 2026. Ce document prépare la livraison ; il ne vaut
ni preuve d'une répétition réalisée ni déclaration de gel définitif.

## Version retenue

Adam a demandé de livrer tout dev, y compris la PR #17, avec le journal de Claude
et les présents documents. Le code de base intégré est
`63456246f6fb89f808a538c831d7dd5fdd809ab9`. Le commit final inclut les documents :
son identifiant sera celui du tag v1.0, à vérifier avec `git rev-parse v1.0^{commit}`.

La PR #17 ajoute un coût estimé en dollars mais retire le seuil de tokens,
agrandit le contexte et retire les dernières améliorations du streaming.
Audit : 342 tests Python réussis, quatre échecs sur le seuil de tokens. Ce résultat
est assumé dans JOURNAL.md ; aucun correctif applicatif n'est ajouté pendant le gel.

## Procédure de gel

1. Paragraphe chasse ouverte finalisé : aucun flag communiqué à Adam au moment du gel ; modalités à demander à l’examinateur.
2. Pousser la même version documentaire finale dans dev puis main.
3. Déployer ce commit sur Netlify et le backend ; vérifier santé et version.
4. Poser et pousser le tag annoté v1.0 sur ce SHA exact, sans le déplacer ensuite.
5. Répéter sur cette version, arrêt strict à cinq minutes, puis lire tout le journal.
   Garder la preuve séparément du dépôt gelé. Aucun changement de code après le gel.

## Répétition réelle — déroulé de cinq minutes

Avant le chrono : ouvrir le site public sans `?demo`, la console de tests dans le
bon dépôt et JOURNAL.md. Vérifier qu'aucune mission d'un autre utilisateur ne tourne.
Préparer un minuteur avec une alarme à 5:00. Les recherches réelles consomment du
crédit ; la réutilisation d'un résultat ne démontre pas un nouvel appel au modèle.

| Temps | Action et preuve à montrer |
| --- | --- |
| 0:00–0:25 | Présenter Lockin : veille documentaire publique, sources, limites, journal. Montrer le tag et le SHA notés avant le départ. |
| 0:25–1:40 | Lancer une veille Rapide avec une durée d'une minute, sujet fourni sur place. Si elle est réutilisée, annoncer le cache ; utiliser une actualisation explicite pour montrer une exécution réelle. Montrer l'outil proposé puis ses arguments et le résultat dans le journal. |
| 1:40–2:30 | Ouvrir les constats et leurs extraits. Expliquer date inconnue, source unique ou absence de constat sans inventer un succès. Montrer tokens, appels et durée ; aucun seuil de tokens n’est appliqué dans cette version ; le prix est une estimation. |
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
