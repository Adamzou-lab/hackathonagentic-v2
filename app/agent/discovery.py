"""Entrées et extraction bornées de la découverte de domaines publics.

La découverte fournit des candidats, pas une certification de fiabilité. Le moteur
vérifie leur DNS avant sélection et le lecteur le vérifie encore à la connexion.
"""
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, field_validator

from app.schemas import StrictModel, normalize_domain
from app.agent.web import ToolFailure


class DiscoveryInput(StrictModel):
    query: str = Field(min_length=1, max_length=500)

    @field_validator('query')
    @classmethod
    def query_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Requête de découverte obligatoire.')
        return value.strip()


class SelectedSource(StrictModel):
    domain: str = Field(min_length=1, max_length=253)
    reason: str = Field(min_length=1, max_length=300)

    @field_validator('domain')
    @classmethod
    def domain_valid(cls, value):
        return normalize_domain(value)

    @field_validator('reason')
    @classmethod
    def reason_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Motif de sélection obligatoire.')
        return value.strip()


class SelectionInput(StrictModel):
    sources: list[SelectedSource] = Field(min_length=1, max_length=5)

    @field_validator('sources')
    @classmethod
    def unique_domains(cls, values):
        if len({source.domain for source in values}) != len(values):
            raise ValueError('Un domaine ne peut être sélectionné deux fois.')
        return values


def normalize_candidate_url(url):
    """Renvoie (domaine, URL HTTPS) sans résolution ni requête réseau.

    Les hôtes ont une syntaxe publique uniquement ; ce contrôle ne remplace pas
    la protection DNS du moteur et du lecteur. Les identifiants, IP, caractères
    ambigus et ports non HTTPS sont rejetés avant toute conservation.
    """
    if (not isinstance(url, str) or not url or len(url) > 2048
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url)
            or '\\' in url):
        raise ToolFailure('blocked_url')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or not parsed.hostname):
            raise ValueError('HTTPS public uniquement')
        domain = normalize_domain(parsed.hostname)
        if domain.endswith(('.home.arpa', '.localdomain', '.onion', '.lan', '.home')):
            raise ValueError('Domaine non public')
        return domain, urlunsplit(('https', domain, parsed.path or '/', parsed.query, ''))
    except (ValueError, TypeError, UnicodeError):
        raise ToolFailure('blocked_url') from None


def extract_candidates(response):
    """Ne conserve que les résultats structurés, jamais les URL inventées en texte."""
    if not isinstance(response, dict) or not isinstance(response.get('content'), list):
        raise ToolFailure('source_discovery_invalid_response')
    candidates, domains = [], set()
    max_uses_reached = False
    safe_errors = {'max_uses_exceeded', 'too_many_requests', 'query_too_long',
                   'unavailable', 'invalid_input'}
    for block in response['content']:
        if not isinstance(block, dict) or block.get('type') != 'web_search_tool_result':
            continue
        content = block.get('content')
        if not isinstance(content, list):
            code = content.get('error_code') if isinstance(content, dict) else None
            safe = code if isinstance(code, str) and code in safe_errors else 'unavailable'
            # Anthropic peut ajouter cette limite après une recherche réussie.
            # On ne masque aucune autre erreur et on exige des candidats valides.
            if safe == 'max_uses_exceeded':
                max_uses_reached = True
                continue
            raise ToolFailure('source_discovery_' + safe)
        for item in content:
            if not isinstance(item, dict) or item.get('type') != 'web_search_result':
                continue
            try:
                domain, url = normalize_candidate_url(item.get('url'))
            except ToolFailure:
                continue
            if domain in domains or len(candidates) >= 10:
                continue
            title = item.get('title', '')
            candidates.append({'domain': domain, 'url': url,
                               'title': title[:200] if isinstance(title, str) else ''})
            domains.add(domain)
    if not candidates:
        if max_uses_reached:
            raise ToolFailure('source_discovery_max_uses_exceeded')
        raise ToolFailure('source_discovery_no_candidates')
    return candidates
