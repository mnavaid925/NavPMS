"""Supplier credit-score connector registry (Module 18, sub-module 2).

Mirrors the freight-carrier (``apps/fulfillment/carriers.py``) pattern: a ``Protocol`` + a
``_CREDIT_REGISTRY`` + an env-selectable default (``settings.CREDIT_PROVIDER``). The bundled
``MockCreditProvider`` derives a deterministic 0-100 credit-health score from the vendor so the
financial-risk monitoring flow can be exercised with no third-party account; real providers
(D&B / Experian / Creditsafe) are added by implementing ``fetch`` against their API and
registering the class.

SECURITY (flagged per the project vulnerability rule):
    A real credit connector calls a provider-supplied endpoint server-side, so its URL MUST be
    SSRF-validated first — HTTPS-only, reject internal IP literals, resolve hostnames and block
    non-routable addresses (honouring ``settings.CREDIT_ALLOWLIST``). Use
    :func:`validate_credit_url` (fail-closed). The bundled ``MockCreditProvider`` makes no network
    calls, so it is safe by construction.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError

from .models import risk_band_from_score


# ---------------------------------------------------------------------------
# Result value object
# ---------------------------------------------------------------------------
@dataclass
class CreditResult:
    ok: bool = True
    provider: str = 'mock'
    score: float = 0.0          # 0-100, higher = healthier
    band: str = 'low'           # low / medium / high / critical risk
    outlook: str = 'stable'     # positive / stable / negative
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SSRF guard (fail-closed) — for a future real HTTP credit connector
# ---------------------------------------------------------------------------
def _allowlist():
    raw = getattr(settings, 'CREDIT_ALLOWLIST', '') or ''
    return {h.strip().lower() for h in raw.split(',') if h.strip()}


def _is_blocked_ip(ip_str):
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def validate_credit_url(url):
    """Raise ``ValidationError`` unless ``url`` is a safe outbound HTTPS target (fail closed)."""
    parsed = urlparse((url or '').strip())
    if parsed.scheme != 'https':
        raise ValidationError('Credit URL must use HTTPS.')
    host = parsed.hostname
    if not host:
        raise ValidationError('Credit URL has no host.')
    if host.lower() in _allowlist():
        return url
    try:
        ipaddress.ip_address(host)
        if _is_blocked_ip(host):
            raise ValidationError('Credit URL host is not a routable address.')
        return url
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationError('Credit URL host could not be resolved.')
    for info in infos:
        if _is_blocked_ip(info[4][0]):
            raise ValidationError('Credit URL resolves to a non-routable address.')
    return url


# ---------------------------------------------------------------------------
# Connector protocol
# ---------------------------------------------------------------------------
class CreditProvider:
    name: str = 'base'

    def fetch(self, vendor) -> CreditResult:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Mock provider (deterministic test double — no network)
# ---------------------------------------------------------------------------
_OUTLOOKS = ('negative', 'stable', 'positive')


class MockCreditProvider:
    """Derives a stable 0-100 score from the vendor's identifiers — no randomness, no network.

    A deterministic spread (15..95) keyed on the vendor's number/name so the seed/test fixtures land
    different vendors in different risk bands, and re-checks are stable unless real inputs change.
    """
    name = 'mock'

    def fetch(self, vendor):
        key = f'{getattr(vendor, "vendor_number", "")}{getattr(vendor, "legal_name", "")}'
        h = sum(ord(c) for c in key) if key else 0
        score = float(15 + (h % 81))          # 15..95
        outlook = _OUTLOOKS[h % 3]
        return CreditResult(
            provider=self.name, score=round(score, 2),
            band=risk_band_from_score(score), outlook=outlook,
            raw={'provider': self.name, 'key_hash': h},
        )


_CREDIT_REGISTRY = {
    'mock': MockCreditProvider,
}


def get_credit_provider(name=None):
    """Return a provider instance for ``name`` (or the env default); unknown names fall back to mock."""
    key = (name or getattr(settings, 'CREDIT_PROVIDER', 'mock') or 'mock')
    cls = _CREDIT_REGISTRY.get(key, MockCreditProvider)
    return cls()
