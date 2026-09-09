"""Passages citables : sous-chaînes exactes du texte effectivement lu."""
import hashlib


def passages(page, limit=24):
    text = page.get('text', '')
    result, start = [], 0
    while start < len(text) and len(result) < limit:
        end = min(start + 450, len(text))
        if end < len(text):
            boundary = text.rfind(' ', start + 200, end)
            if boundary > start:
                end = boundary
        quote = text[start:end].strip()
        if len(quote) >= 10:
            pid = hashlib.sha256((page['source_id'] + '\0' + quote).encode()).hexdigest()[:20]
            result.append({'passage_id':pid, 'quote':quote})
        start = end
    return result


def context_passages(page, subject, limit=4):
    """Rank exact excerpts locally; this selects data, never an agent action."""
    import re
    ignored = {'les','des','une','dans','pour','avec','sur','the','and','for','veille',
               'recherche','nouveautes','nouveautés','outils'}
    terms = set(re.findall(r"[^\W_]+", subject.casefold())) - ignored
    terms = {t for t in terms if len(t) >= 3}
    items = passages(page)
    if len(items) <= limit:
        return items
    scores = [len(terms & set(re.findall(r"[^\W_]+", item['quote'].casefold()))) for item in items]
    # Include spread-out excerpts when lexical matching is unavailable (e.g. another language).
    anchors = [round(i * (len(items)-1) / (limit-1)) for i in range(limit)]
    ranked = sorted(range(len(items)), key=lambda i: (-scores[i], 0 if i in anchors else 1, i))
    return [items[i] for i in sorted(ranked[:limit])]
