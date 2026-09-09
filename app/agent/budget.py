"""Budget policy: research cannot spend the reserve needed to save evidence."""

def limits(actions, auto_sources=False):
    minimum_research = 3 if auto_sources else 1
    reserve = min(3, max(1, actions // 4), max(0, actions - minimum_research))
    tokens = 16000 if actions <= 10 else (24000 if actions <= 20 else 40000)
    # Native web discovery bills retrieved content before the first page read.
    # Keep the finalization margin usable after this bootstrap cost.
    return {'finalization_reserve': reserve, 'research_action_limit': actions - reserve,
            'web_search_limit': 1 if actions <= 10 else (2 if actions <= 20 else 4),
            'token_budget': tokens + (16000 if auto_sources else 0)}


def observed_tokens(events):
    total = 0
    for event in events:
        if event['kind'] != 'model_finished':
            continue
        usage = event['data'].get('usage') or {}
        if not isinstance(usage, dict):
            continue
        for key in ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'):
            value = usage.get(key)
            if type(value) is int and value >= 0:
                total += value
    return total
