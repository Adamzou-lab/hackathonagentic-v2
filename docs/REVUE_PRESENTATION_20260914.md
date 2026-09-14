# Revue et préparation de la présentation du 15 septembre

## Budgets

| Pack | Sources automatiques | Sources manuelles | Recherches web payantes max. |
|---|---:|---:|---:|
| Rapide (10 actions) | 80 000 tokens | 64 000 | 1 |
| Standard (20 actions) | 128 000 tokens | 112 000 | 2 |
| Approfondi (100 actions) | 192 000 tokens | 176 000 | 4 |

Les limites sont des plafonds, pas des objectifs de consommation. La réserve de
finalisation et l'arrêt anticipé après deux constats en Rapide restent actifs.
Le coût exact dépend des tokens d'entrée/sortie, du cache et de la recherche web.
Le dernier appel peut dépasser le seuil mesuré entre appels. Les 4 € indiqués par
l'opérateur ne constituent ni un solde vérifié ni une limite globale du programme.

## Boucle de correction

Chaque défaut ci-dessous a été reproduit par un test rouge, corrigé, puis revérifié
avec les tests existants. Aucune relance payante automatique de la revue.

Résultat local : 382 tests Python et 14 tests frontend réussis ; évaluation 10/10.

| Défaut observé | Correction | Preuve |
|---|---|---|
| Une reprise pouvait rétablir des domaines manuels supprimés | Filtrer chaque page selon les permissions actuelles ; jamais remplacer les domaines manuels | `test_resumed_pages_cannot_expand_scope_or_reset_freshness[narrowed]` |
| Des reprises successives rajeunissaient le cache | Âge contrôlé depuis `retrieved_at` original, six heures maximum ; date absente/invalide exclue | variantes `expired`, `missing_date` |
| Un autre sujet pouvait récupérer les mêmes pages | Reprise des pages uniquement pour le même sujet normalisé et le même mode de sources | variante `other_subject` |
| Une preuve hors périmètre déjà stockée était acceptée | Revérifier l'URL au contrôle sémantique et à la sauvegarde | `test_evidence_from_disallowed_cached_domain_is_blocked` |
| Tous les articles d'un flux pouvaient recevoir la date du premier | Date par entrée dans le texte ; aucune date globale pour un flux multi-articles | `test_feed_does_not_date_old_entries_as_new` |
| Entités XML acceptées dans les flux | Rejeter DTD et déclarations d'entités avant le parseur | `test_feed_dtd_is_rejected` |
| Champ de réserves sans borne de longueur | 500 caractères maximum par réserve, cinq réserves | `test_caveats_cannot_bloat_provider_context` |
| Protocole de rejet moins strict que son schéma | Rejeter les champs supplémentaires | `test_rejection_protocol_rejects_extra_fields` |
| Recherche refusée pour préserver le budget transformée en panne fatale générique | Conserver `web_search_budget_reserved` et permettre la finalisation | `test_reserved_budget_is_not_mislabeled_as_fatal_crash` |

## Validation réelle et blocage

Le 14 septembre, les deux essais locaux et les deux essais isolés sur le VPS
(veille puis requête hostile) ont chacun reçu `anthropic_http_401`, avant le
premier appel d'outil. La clé locale et la clé serveur ont été refusées. Aucun
constat n'a été inventé. Les missions ont un statut `failed` et une trace de panne.
Les réponses ne contiennent aucun relevé de tokens : ne pas annoncer un coût nul
mesuré. Aucun nouvel essai payant n'est lancé tant que la clé n'est pas corrigée.
Adam confirme le 14 septembre qu'il demandera une nouvelle clé avant la démo.

Demain : remplacer `ANTHROPIC_API_KEY` dans `/etc/lockin/lockin.env` sur le VPS,
puis redémarrer uniquement le service `lockin`. Aucun secret dans Netlify ou Git.
Remplacer aussi la clé du `.env` local seulement si une répétition locale est
souhaitée. Tester ensuite une vraie veille avant de partager le lien avec la salle.

`/health` valide le service et le stockage. `provider_ready` signifie qu'une clé
est configurée ; il ne prouve pas que le fournisseur l'accepte.

Les tests automatisés utilisent des fournisseurs substitués. Ils ne valident pas
le crédit ni le comportement du vrai modèle. La démo réelle n'est pas validée
tant qu'une veille n'a pas été répétée avec une clé acceptée.

## Répétition à faire après rétablissement de la clé

Depuis la racine du dépôt, avec les dépendances installées :

```sh
.venv/bin/python -m pytest tests -q
.venv/bin/python eval.py
.venv/bin/python scripts/rehearse_live.py --config .env --output /tmp/lockin-repetition-finale
```

La dernière commande consomme du crédit : une veille de deux minutes maximum,
puis une requête hostile d'une minute maximum, sur une base isolée. Elle conserve
le journal, le temps du premier fragment, les tokens, le coût estimé et les erreurs.
Ne pas répéter la commande en boucle sans lire les résultats.

## Déroulé de cinq minutes

1. **0:00–0:30** : présenter le sujet, choisir Rapide et les sources automatiques.
2. **0:30–2:30** : lancer une recherche inédite ; montrer les outils et les sources
   dans le journal, puis la synthèse et ses limites. Si échec, montrer l'erreur.
3. **2:30–3:15** : retrouver la veille dans Mes veilles, expliquer la réutilisation
   gratuite et l'actualisation volontaire.
4. **3:15–4:00** : couper l'API puis tenter un lancement ; montrer le refus et son
   horodatage, réactiver ensuite. Cela teste la coupure logique, pas la révocation
   réelle de la clé chez Anthropic.
5. **4:00–5:00** : montrer l'arrêt et l'évaluation automatisée 10 scénarios ; préciser
   que cette évaluation utilise des doubles et ne consomme pas de crédit.

Répétition publique chronométrée encore à effectuer : le fournisseur refusait la clé
pendant cette revue. Ne pas présenter ce déroulé comme une répétition déjà réussie.

## Limites assumées

Le service public est un espace partagé, avec une seule mission simultanée et
un interrupteur global volontairement accessible pour l'examinateur. Il n'isole
pas les utilisateurs et ne limite pas la dépense cumulée du compte. Éviter de
demander à toute la salle de lancer simultanément des veilles. Les contrôles
sémantiques réduisent les inventions sans garantir la vérité des sources.
