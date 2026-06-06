"""Restricted-party screening connector registry (Module 18, sub-module 1).

Mirrors the pluggable freight-carrier (``apps/fulfillment/carriers.py``) and punch-out
(``apps/catalog/punchout.py``) patterns: a ``Protocol`` + a ``_SCREENING_REGISTRY`` + an
env-selectable default (``settings.SCREENING_PROVIDER``). The bundled ``MockScreeningProvider``
deterministically fuzzy-matches a screened name against the tenant's ``RestrictedPartyEntry`` rows
so the whole flow can be exercised with no remote account; real providers (OFAC / SAM / Dow Jones)
are added by implementing ``screen`` against their API and registering the class.

SECURITY (flagged per the project vulnerability rule):
    A real screening connector calls an operator-/provider-supplied endpoint server-side. Like the
    punch-out setup URL and carrier tracking endpoint, that URL MUST be SSRF-validated before the
    request — HTTPS-only, reject raw internal IP literals, and resolve hostnames, blocking any that
    map to a non-routable address (honouring ``settings.SCREENING_ALLOWLIST``). Use
    :func:`validate_screening_url` (fail-closed) and never request an unvalidated URL. The bundled
    ``MockScreeningProvider`` makes no network calls, so it is safe by construction.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Result value objects
# ---------------------------------------------------------------------------
@dataclass
class MatchHit:
    """One restricted-party match produced by a screening run."""
    matched_name: str
    list_name: str = ''
    score: float = 0.0
    matched_field: str = 'name'
    entry_id: object = None


@dataclass
class ScreeningResult:
    ok: bool = True
    provider: str = 'mock'
    matches: list = field(default_factory=list)
    lists_checked: list = field(default_factory=list)
    message: str = ''


# ---------------------------------------------------------------------------
# SSRF guard (fail-closed) — for a future real HTTP screening connector
# ---------------------------------------------------------------------------
def _allowlist():
    raw = getattr(settings, 'SCREENING_ALLOWLIST', '') or ''
    return {h.strip().lower() for h in raw.split(',') if h.strip()}


def _is_blocked_ip(ip_str):
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable — treat as unsafe
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def validate_screening_url(url):
    """Raise ``ValidationError`` unless ``url`` is a safe outbound HTTPS target.

    WARNING (SSRF): a screening-provider endpoint is config-supplied and requested server-side.
    Without this guard an attacker could point it at ``http://169.254.169.254/`` or an internal
    host. Secure pattern: HTTPS-only, reject raw internal IP literals, and resolve hostnames —
    blocking any that map to a non-routable address. Fail closed.
    """
    parsed = urlparse((url or '').strip())
    if parsed.scheme != 'https':
        raise ValidationError('Screening URL must use HTTPS.')
    host = parsed.hostname
    if not host:
        raise ValidationError('Screening URL has no host.')
    if host.lower() in _allowlist():
        return url
    try:
        ipaddress.ip_address(host)
        if _is_blocked_ip(host):
            raise ValidationError('Screening URL host is not a routable address.')
        return url
    except ValueError:
        pass  # hostname — resolve it
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationError('Screening URL host could not be resolved.')
    for info in infos:
        if _is_blocked_ip(info[4][0]):
            raise ValidationError('Screening URL resolves to a non-routable address.')
    return url


# ---------------------------------------------------------------------------
# Connector protocol
# ---------------------------------------------------------------------------
class ScreeningProvider:
    name: str = 'base'

    def screen(self, name, *, tenant, lists=None, threshold=85.0) -> ScreeningResult:  # pragma: no cover
        raise NotImplementedError


def _norm(s):
    return ' '.join((s or '').lower().split())


def _ratio(a, b):
    return SequenceMatcher(None, a, b).ratio() * 100.0


# ---------------------------------------------------------------------------
# Mock provider (deterministic test double — no network)
# ---------------------------------------------------------------------------
class MockScreeningProvider:
    """Fuzzy-matches the screened name against the tenant's active ``RestrictedPartyEntry`` rows.

    Deterministic (``difflib`` ratio, no randomness): the same name + lists always returns the same
    matches, so seeds and tests can guarantee a hit by listing a vendor's legal name.
    """
    name = 'mock'

    def screen(self, name, *, tenant, lists=None, threshold=85.0):
        from .models import RestrictedPartyEntry  # lazy — avoid import cycle

        target = _norm(name)
        if not target:
            return ScreeningResult(provider=self.name, message='Empty name.')
        qs = RestrictedPartyEntry.all_objects.filter(tenant=tenant, is_active=True)
        if lists:
            qs = qs.filter(list_name__in=lists)
        checked = sorted({e.list_name for e in qs})
        matches = []
        for entry in qs:
            best = _ratio(target, _norm(entry.entity_name))
            matched_field = 'name'
            for alias in (entry.aliases or []):
                r = _ratio(target, _norm(alias))
                if r > best:
                    best, matched_field = r, 'alias'
            if best >= float(threshold):
                matches.append(MatchHit(
                    matched_name=entry.entity_name, list_name=entry.list_name,
                    score=round(best, 2), matched_field=matched_field, entry_id=entry.id,
                ))
        matches.sort(key=lambda m: m.score, reverse=True)
        return ScreeningResult(
            provider=self.name, matches=matches, lists_checked=checked,
            message=f'{len(matches)} match(es) over {threshold}%.',
        )


_SCREENING_REGISTRY = {
    'mock': MockScreeningProvider,
}


def get_screening_provider(name=None):
    """Return a provider instance for ``name`` (or the env default).

    Unknown names fall back to the mock provider, mirroring the carrier / gateway registries.
    """
    key = (name or getattr(settings, 'SCREENING_PROVIDER', 'mock') or 'mock')
    cls = _SCREENING_REGISTRY.get(key, MockScreeningProvider)
    return cls()
