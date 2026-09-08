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
