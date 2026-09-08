# Palier 5 — partie Codex

## Vérifications exécutées le 8 septembre 2026

Les tests de `tests/test_palier5_reliability.py` utilisent le vrai stockage et la
validation des constats avec des pages contrôlées. Aucun appel au modèle ni au
réseau. Ils ne démontrent donc pas la capacité de Haiku à détecter une injection.

| Tentative | Résultat attendu et observé |
| --- | --- |
| Deux pages d'un même site présentées comme corroborées | Confiance abaissée à `single_source`, limite explicite |
| Variante www pour simuler une seconde source | Même réduction de confiance |
| Même citation recopiée sur deux domaines | Même réduction de confiance |
| Contradiction signalée sur un seul site | État `conflicting` conservé |
| Date inventée sans métadonnée justificative | Date supprimée, statut `unknown` |
| Citation absente du texte lu | `invalid_evidence`, aucun constat sauvegardé |
| Appel interrompu, bilan absent, tokens négatifs ou booléens | Total indisponible ; mesures partielles conservées |
| Deux réponses avec tokens de cache | Somme correcte, sans duplication à la relecture |
| Aucun appel commencé | Total de zéro disponible |

Le prompt demande de ne pas adopter une prémisse comme vraie, d'attribuer les
annonces à leurs auteurs et d'expliciter les contradictions. Les sujets incohérents
nécessitent une clarification. Ce sont des consignes au modèle, pas un routage par
mots-clés. Les contrôles HTTP relèvent de Claude.

### Limites à présenter honnêtement

Une citation exacte ne garantit pas que le résumé en respecte le sens. Deux domaines
ne garantissent pas deux éditeurs indépendants ; sous-domaines et reprises restent
à interpréter par le modèle. Aucun score de vérité universel n'est promis. Les
modifications de prompt doivent encore être éprouvées sur des requêtes réelles.

## Contrat pour Panaki : `snapshot.usage`

Disponible dans la réponse de détail d'une mission, sans appel IA supplémentaire.

```json
{
  "model_calls": 2,
  "actions": 1,
  "network_requests": 2,
  "elapsed_seconds": 12,
  "measured_calls": 2,
  "unmeasured_calls": 0,
  "tokens_complete": true,
  "tokens": {
    "input_tokens": 15,
    "output_tokens": 5,
    "cache_creation_input_tokens": 30,
    "cache_read_input_tokens": 20
  },
  "observed_tokens": {
    "input_tokens": 15,
    "output_tokens": 5,
    "cache_creation_input_tokens": 30,
    "cache_read_input_tokens": 20
  },
  "total_tokens": 70
}
```

- `model_calls` compte les tentatives réservées, y compris les échecs ; ce n'est pas
  une preuve de facturation. `network_requests` compte les réservations réseau.
- `tokens_complete=false` : `tokens` et `total_tokens` sont `null`. Afficher
  « consommation incomplète » ; `observed_tokens` contient seulement les appels mesurés.
- En cours d'appel, le total peut être indisponible puis devenir complet à réception.
- Les deux champs de cache sont séparés des tokens d'entrée non mis en cache.
- Sur réutilisation d'une veille, le bilan est celui de la mission historique.
  N'afficher « aucun nouvel appel IA » que si la réponse de création signale la
  réutilisation ; ne pas présenter les anciens tokens comme une nouvelle dépense.
- Aucun prix en euros n'est calculé. Les tokens, appels et durée sont mesurés ; un
  éventuel prix devra distinguer tokens, cache et recherche web selon le tarif utilisé.

## Validation

Suite Python : 286 tests réussis. Évaluation autonome : 10/10 après adaptation du
scénario nominal à la réduction de confiance (ses deux pages sont du même site).
Le bonus a été repris par Codex : le bloc « Coût de cette requête » affiche les
tokens, les appels et la durée, pendant la mission et dans ses résultats conservés.
Il distingue les mesures incomplètes et la réutilisation d'une mission. Aucun prix
monétaire n'est inventé. Vérification visuelle locale en mode démonstration et
7 contrôles de présentation avec `node tests/frontend_usage.test.cjs`.
Suite intégrée avec Claude : 338 tests Python et 12 tests frontend existants réussis.
Le déploiement public de ce bonus reste à effectuer.
