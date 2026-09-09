"""Codes publics stables : jamais le texte d'une exception ou d'une réponse API."""
import re

import aiohttp
import httpx
from pydantic import ValidationError

from app.agent.web import ToolFailure


def failure_code(exc, dependency='tool'):
    if isinstance(exc, ToolFailure):
        # Tous les codes sont produits par l'application ; même un adaptateur
        # défectueux ne doit pas transformer une exception en fuite de secrets.
        code = exc.code
        allowed = {
            'timeout', 'unavailable', 'rate_limited', 'blocked_url', 'invalid_input',
            'robots_unavailable', 'robots_denied', 'too_large', 'redirect_limit',
            'document_redirect_rejected', 'unsupported_content', 'attempts_exhausted',
            'invalid_evidence', 'unsupported_claim', 'idempotency_conflict', 'unknown_related_finding',
            'related_finding_superseded', 'tool_disabled_for_test', 'unknown_tool',
            'sources_not_selected', 'source_discovery_not_allowed',
            'source_selection_not_allowed', 'source_not_discovered', 'source_dns_unavailable',
            'invalid_scope_decision', 'invalid_finish', 'execution_error', 'cancellation_unconfirmed',
            'anthropic_timeout', 'anthropic_network_error', 'anthropic_invalid_response',
            'anthropic_incomplete_response',
            'anthropic_stream_error', 'anthropic_stream_interrupted', 'anthropic_key_missing',
        }
        for prefix in ('source_discovery_', 'web_search_'):
            allowed.update(prefix + suffix for suffix in (
                'unavailable', 'invalid_response', 'no_candidates', 'max_uses_exceeded',
                'too_many_requests', 'query_too_long', 'invalid_input'))
        return code if isinstance(code, str) and (code in allowed or
            re.fullmatch(r'anthropic_http_[1-5][0-9]{2}', code)) else 'execution_error'
    if isinstance(exc, httpx.TimeoutException):
        return 'anthropic_timeout'
    if isinstance(exc, httpx.RequestError):
        return 'anthropic_network_error'
    if isinstance(exc, TimeoutError):
        return 'timeout'
    if isinstance(exc, (aiohttp.ClientError, OSError)):
        return 'source_dns_unavailable' if dependency == 'dns' else 'unavailable'
    if isinstance(exc, ValidationError):
        return 'invalid_input'
    return 'execution_error'


def must_stop(operation, code, dependency='tool'):
    """Une panne du modèle interdit une nouvelle décision payante de récupération.

    Une page isolée peut échouer : le modèle reçoit l'erreur, toujours sous les
    mêmes budgets et la limite existante de deux tentatives par URL.
    """
    return (operation in {'decide', 'discover_sources'} or
            code.startswith('anthropic_') or code.startswith('source_discovery_') or
            code in {'execution_error', 'cancellation_unconfirmed', 'web_search_unavailable', 'web_search_too_many_requests'} or
            (dependency == 'model_provider' and code in {'timeout', 'unavailable'}))
