"""Freight-carrier connector registry (Module 12, sub-module 2).

Mirrors the pluggable payment-gateway (``apps/tenants/gateways.py``) and punch-out
(``apps/catalog/punchout.py``) patterns: a ``Protocol`` + a ``_CARRIER_REGISTRY`` +
an env-selectable default (``settings.FREIGHT_CARRIER``). A ``MockCarrier`` produces a
deterministic tracking progression so the whole sync flow can be exercised without a
live carrier account; real carriers (FedEx / UPS / DHL) are added by implementing
``fetch_tracking`` against their API and registering the class.

Generic, carrier-agnostic status codes flow back to the service layer, which maps them
to the ``Shipment`` status:

    label_created -> advised
    picked_up / in_transit -> in_transit
    out_for_delivery -> out_for_delivery
    delivered -> delivered

SECURITY (flagged per the project vulnerability rule):
    A real HTTP carrier connector fetches an operator-/carrier-supplied endpoint
    server-side. Like the punch-out setup URL, that endpoint MUST be SSRF-validated
    before the request — HTTPS-only, reject raw internal IP literals, and resolve
    hostnames, blocking any that map to a non-routable address (honouring
    ``settings.FREIGHT_TRACKING_ALLOWLIST``). Use :func:`validate_carrier_url` below
    (fail-closed) and never request an unvalidated URL. The bundled ``MockCarrier``
    makes no network calls, so it is safe by construction.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Optional, Protocol
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


# ---------------------------------------------------------------------------
# Result value objects
# ---------------------------------------------------------------------------
@dataclass
class TrackingUpdate:
    """A single carrier scan event."""
    status_code: str
    description: str = ''
    location: str = ''
    occurred_at: Optional[datetime] = None
    raw: dict = field(default_factory=dict)


@dataclass
class TrackingResult:
    ok: bool = True
    current_status: str = ''                 # carrier status code of the latest update
    estimated_delivery: object = None        # date or None
    updates: list = field(default_factory=list)
    message: str = ''


# ---------------------------------------------------------------------------
# SSRF guard (fail-closed) — for a future real HTTP carrier connector
# ---------------------------------------------------------------------------
def _allowlist():
    raw = getattr(settings, 'FREIGHT_TRACKING_ALLOWLIST', '') or ''
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


def validate_carrier_url(url):
    """Raise ``ValidationError`` unless ``url`` is a safe outbound HTTPS target.

    WARNING (SSRF): a carrier tracking endpoint is config-supplied and then
    requested server-side. Without this guard an attacker could point it at
    ``http://169.254.169.254/`` or an internal host. Secure pattern: HTTPS-only,
    reject raw internal IP literals, and resolve hostnames — blocking any that map
    to a non-routable address. Fail closed.
    """
    parsed = urlparse((url or '').strip())
    if parsed.scheme != 'https':
        raise ValidationError('Carrier URL must use HTTPS.')
    host = parsed.hostname
    if not host:
        raise ValidationError('Carrier URL has no host.')
    if host.lower() in _allowlist():
        return url
    try:
        ipaddress.ip_address(host)
        if _is_blocked_ip(host):
            raise ValidationError('Carrier URL host is not a routable address.')
        return url
    except ValueError:
        pass  # hostname — resolve it
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationError('Carrier URL host could not be resolved.')
    for info in infos:
        if _is_blocked_ip(info[4][0]):
            raise ValidationError('Carrier URL resolves to a non-routable address.')
    return url


# ---------------------------------------------------------------------------
# Connector protocol
# ---------------------------------------------------------------------------
class CarrierConnector(Protocol):
    name: str

    def fetch_tracking(
        self, tracking_number: str, *, service_level: str = '', ship_date=None,
    ) -> TrackingResult: ...


def _aware(d, hour=12):
    """A timezone-aware datetime at ``hour`` on date ``d``."""
    dt = datetime.combine(d, time(hour, 0))
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


# ---------------------------------------------------------------------------
# Mock carrier (deterministic test double — no network)
# ---------------------------------------------------------------------------
class MockCarrier:
    """A deterministic carrier whose progression is derived from the ship date.

    Milestones land on ship_date + {0, 1, 2, 3} days; only those whose offset has
    elapsed (relative to today) are returned, so repeated syncs advance smoothly and
    tests can drive any stage by choosing ``ship_date``. No randomness — stable.
    """
    name = 'mock'

    # offset-days -> (status_code, description)
    _MILESTONES = [
        (0, 'picked_up', 'Shipment picked up by carrier'),
        (1, 'in_transit', 'In transit'),
        (2, 'out_for_delivery', 'Out for delivery'),
        (3, 'delivered', 'Delivered'),
    ]

    def fetch_tracking(self, tracking_number, *, service_level='', ship_date=None):
        if not tracking_number:
            return TrackingResult(ok=False, message='No tracking number.')
        base = ship_date or timezone.localdate()
        today = timezone.localdate()
        elapsed = (today - base).days
        updates = []
        current = 'label_created'
        for offset, code, desc in self._MILESTONES:
            if offset <= elapsed:
                updates.append(TrackingUpdate(
                    status_code=code, description=desc,
                    location='Distribution center' if code != 'delivered' else 'Destination',
                    occurred_at=_aware(base + timedelta(days=offset)),
                    raw={'carrier': self.name, 'tracking_number': tracking_number,
                         'milestone': code},
                ))
                current = code
        return TrackingResult(
            ok=True, current_status=current,
            estimated_delivery=base + timedelta(days=3), updates=updates,
        )


_CARRIER_REGISTRY = {
    'mock': MockCarrier,
}


def get_carrier(name=None):
    """Return a connector instance for ``name`` (or the env default).

    Unknown names fall back to the mock carrier, mirroring the payment-gateway
    registry's defensive default.
    """
    key = (name or getattr(settings, 'FREIGHT_CARRIER', 'mock') or 'mock')
    cls = _CARRIER_REGISTRY.get(key, MockCarrier)
    return cls()
