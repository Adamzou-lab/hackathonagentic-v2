"""Measured usage only: interrupted or malformed reports never imply zero tokens."""

TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')


def usage_summary(data, events, elapsed):
    reports = [e['data'].get('usage') for e in events if e['kind'] == 'model_finished']
    totals = {key: 0 for key in TOKEN_FIELDS}
    measured = 0
    for report in reports:
        if not isinstance(report, dict):
            continue
        values = {key: report.get(key, 0 if key.startswith('cache_') else None) for key in TOKEN_FIELDS}
        if any(type(value) is not int or value < 0 for value in values.values()):
            continue
        measured += 1
        for key, value in values.items():
            totals[key] += value
    calls = data['model_calls_used']
    complete = measured == calls == len(reports)
    return {
        'model_calls': calls, 'actions': data['actions_used'],
        'network_requests': data['network_requests_used'], 'elapsed_seconds': elapsed,
        'measured_calls': measured, 'unmeasured_calls': max(0, calls - measured),
        'tokens_complete': complete,
        'tokens': totals if complete else None,
        'observed_tokens': totals if measured else None,
        'total_tokens': sum(totals.values()) if complete else None,
    }
