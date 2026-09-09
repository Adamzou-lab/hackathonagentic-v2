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


def finalization_token_reserve(events, ceiling):
    """Reserve one decision from recent measured decisions, not native web payloads."""
    measured = []
    for event in events:
        data = event.get('data', {})
        if event.get('kind') != 'model_finished' or not data.get('proposed_action'):
            continue
        usage = data.get('usage') or {}
        if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0
                for k in ('input_tokens', 'output_tokens')):
            continue
        measured.append(observed_tokens([event]))
    if not measured:
        return int(ceiling * .30)
    # One final proposal plus its semantic verification. No bigger total budget.
    return min(ceiling, max(8192, int(max(measured[-3:]) * 1.5) + 4096))


def additional_web_search_fits(events, ceiling):
    """Avoid another native search when measured costs would consume finalization."""
    native = [observed_tokens([e]) for e in events if e.get('kind') == 'model_finished'
              and not e.get('data', {}).get('proposed_action')
              and isinstance(e.get('data', {}).get('usage'), dict)
              and isinstance(e['data']['usage'].get('server_tool_use'), dict)
              and type(e['data']['usage']['server_tool_use'].get('web_search_requests')) is int
              and e['data']['usage']['server_tool_use']['web_search_requests'] > 0]
    if not native:
        return True  # First search has no measured baseline yet.
    estimate = max(12000, int(max(native) * 1.5))
    return observed_tokens(events) + estimate + finalization_token_reserve(events, ceiling) < ceiling
