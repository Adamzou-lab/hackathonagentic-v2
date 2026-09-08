"""Calcul transparent du coût d'une requête Anthropic terminée."""


# Tarifs publics Haiku 4.5 en USD, par million de jetons.
# La recherche web est facturée 10 USD / 1 000 recherches.
HAIKU_45 = {
    'input_per_mtok': 1.0,
    'output_per_mtok': 5.0,
    'cache_write_per_mtok': 1.25,
    'cache_read_per_mtok': 0.10,
    'web_search_each': 0.01,
}


def _count(value):
    """Retourne un compteur fournisseur sûr, sans accepter booléens ou négatifs."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _rates(model):
    normalized = (model or '').lower()
    return HAIKU_45 if 'claude-haiku-4-5' in normalized else None


def estimate_request_cost(model, usage):
    """Construit le relevé public de la dernière requête, ou None sans métrique.

    Un modèle inconnu conserve les jetons observés mais renvoie amount_usd=None :
    l'application préfère signaler l'absence de tarif plutôt qu'inventer un coût.
    """
    if not isinstance(usage, dict):
        return None
    server = usage.get('server_tool_use', {})
    server = server if isinstance(server, dict) else {}
    counts = {
        'input_tokens': _count(usage.get('input_tokens')),
        'output_tokens': _count(usage.get('output_tokens')),
        'cache_creation_input_tokens': _count(usage.get('cache_creation_input_tokens')),
        'cache_read_input_tokens': _count(usage.get('cache_read_input_tokens')),
        'web_search_requests': _count(server.get('web_search_requests')),
    }
    if not any(counts.values()):
        return None
    rates = _rates(model)
    amount = None
    if rates:
        amount = (
            counts['input_tokens'] * rates['input_per_mtok'] / 1_000_000
            + counts['output_tokens'] * rates['output_per_mtok'] / 1_000_000
            + counts['cache_creation_input_tokens'] * rates['cache_write_per_mtok'] / 1_000_000
            + counts['cache_read_input_tokens'] * rates['cache_read_per_mtok'] / 1_000_000
            + counts['web_search_requests'] * rates['web_search_each']
        )
    return {
        'model': model or 'unknown',
        'currency': 'USD',
        'amount_usd': round(amount, 8) if amount is not None else None,
        'estimated': amount is not None,
        **counts,
    }
