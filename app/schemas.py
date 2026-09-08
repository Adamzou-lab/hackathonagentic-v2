"""Contrats publics et entrées d'outils strictement bornés."""
import ipaddress
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_domain(value: str) -> str:
    value = value.strip().lower().rstrip('.').encode('idna').decode('ascii')
    if len(value) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', value):
        raise ValueError('Indiquer un nom de domaine public, sans URL ni joker.')
    if value.endswith(('.localhost', '.local', '.internal', '.test', '.invalid')):
        raise ValueError('Domaine non public.')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError('Les adresses IP ne sont pas autorisées.')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class MissionInput(StrictModel):
    subject: str = Field(min_length=1, max_length=500)
    domains: list[str] = Field(default_factory=list, max_length=5)
    auto_sources: bool = False
    watch_id: str | None = Field(default=None, min_length=1, max_length=64)
    force_refresh: bool = False
    allow_new: bool = False
    action_budget: int = Field(default=20, ge=1, le=100)
    duration_minutes: int = Field(default=10, ge=1, le=30)

    @model_validator(mode='after')
    def source_mode(self):
        if self.auto_sources and self.domains:
            raise ValueError('En mode automatique, les domaines sont choisis par l’agent.')
        if not self.auto_sources and not self.domains:
            raise ValueError('Choisissez les sources automatiques ou au moins un domaine.')
        return self

    @field_validator('subject')
    @classmethod
    def subject_not_blank(cls, value):
        if not value.strip():
            raise ValueError('Sujet obligatoire.')
        return value.strip()

    @field_validator('domains')
    @classmethod
    def domains_valid(cls, values):
        return list(dict.fromkeys(normalize_domain(v) for v in values))


class SearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(ge=1, le=5)


class ReadInput(StrictModel):
    url: str = Field(min_length=1, max_length=2048)


class Evidence(StrictModel):
    source_id: str = Field(max_length=64)
    quote: str | None = Field(default=None, min_length=10, max_length=500)
    passage_id: str | None = Field(default=None, min_length=20, max_length=20)

    @model_validator(mode='after')
    def one_reference(self):
        if (self.quote is None) == (self.passage_id is None):
            raise ValueError('Fournir passage_id ou quote, exclusivement.')
        return self


class FindingDraft(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    developer_impact: str = Field(min_length=1, max_length=1000)
    evidence: list[Evidence] = Field(min_length=1, max_length=5)
    event_date: str | None = Field(default=None, max_length=40)
    date_status: Literal['in_window', 'outside_window', 'unknown'] = 'unknown'
    confidence: Literal['single_source', 'corroborated', 'conflicting'] = 'single_source'
    caveats: list[str] = Field(default_factory=list, max_length=5)


class SaveInput(StrictModel):
    change: Literal['new', 'update', 'duplicate'] = 'new'
    related_finding_id: str | None = Field(default=None, min_length=1, max_length=100)
    finding: FindingDraft
    idempotency_key: str = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def relationship(self):
        if (self.change == 'new') != (self.related_finding_id is None):
            raise ValueError('Une évolution ou un doublon doit référencer un constat connu.')
        return self
