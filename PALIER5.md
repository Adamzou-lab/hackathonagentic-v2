# Palier 5 — Durcissement

## Carte bonus : coût affiché

Le coût estimé de la dernière requête terminée est visible dans l'écran de suivi.
Il est calculé côté serveur à partir des métriques Anthropic, puis persisté avec
la mission et son événement `model_finished`. Le détail montre les jetons d'entrée,
de sortie, le cache éventuel et les recherches web facturées.

Le montant est une estimation en USD au tarif public de Haiku 4.5. Un modèle dont
le tarif n'est pas configuré affiche ses compteurs avec « Indisponible » : le
système n'invente jamais un prix.

## Tentatives volontaires de casse

| Essai | Comportement attendu et vérifié |
| --- | --- |
| Entrée vide ou composée d'espaces | Refus HTTP 422 avant tout appel au modèle. |
| Domaine interne, IP, URL avec identifiants ou sous-domaine non autorisé | Refus HTTP 422 ou refus de l'outil ; aucun accès réseau. |
| Paramètres d'outil absurdes ou hors schéma | Action journalisée comme invalide, sans exécution silencieuse. |
| Preuve inventée ou citation absente de la page | Constat rejeté avec `invalid_evidence`. |
| Modèle sans tarif connu | Jetons affichés, coût « Indisponible ». |
| Métriques négatives, booléennes ou mal formées | Compteurs ignorés ; aucun coût négatif ou trompeur. |
| Panne fournisseur, délai dépassé ou arrêt pendant un appel | État explicite, action fermée, résultats déjà validés conservés. |
| Outil désactivé pendant le checkpoint | Échec visible, aucun résultat fabriqué. |

Commande de vérification : `python -m pytest -q`, puis `node --test tests/*.test.cjs`.
Le mode `--demo` permet de vérifier visuellement la carte sans consommer de crédit.
