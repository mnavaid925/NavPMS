"""Module 21 shared validators: a fail-closed SSRF guard + secret masking.

The SSRF guard is the same fail-closed pattern proven in ``apps/compliance/screening.py`` —
HTTPS-only, explicit host allowlist, reject internal IP literals, resolve hostnames and block any
that map to a non-routable address. It is parameterised by *which* settings allowlist to read so the
webhook target URL and the SSO metadata URL can share one implementation.

WARNING (SSRF): both a webhook ``target_url`` and an SSO ``metadata_url`` are operator-supplied and
fetched server-side. Without this guard an attacker who can configure one could point it at
``http://169.254.169.254/`` (cloud metadata) or an internal host. Fail closed.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError

from .models import SECRET_MASK


def mask_secret(value):
    """Return the display mask for any non-empty stored secret (never the real value)."""
    return SECRET_MASK if value else ''


def _allowlist(setting_name):
    raw = getattr(settings, setting_name, '') or ''
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


def validate_outbound_url(url, *, allowlist_setting, label='URL'):
    """Raise ``ValidationError`` unless ``url`` is a safe outbound HTTPS target.

    HTTPS-only; a host listed in the ``allowlist_setting`` comma-separated setting is allowed as-is;
    raw IP literals must be routable; hostnames are resolved and rejected if any A/AAAA record maps
    to a non-routable address. Fail closed.
    """
    parsed = urlparse((url or '').strip())
    if parsed.scheme != 'https':
        raise ValidationError(f'{label} must use HTTPS.')
    host = parsed.hostname
    if not host:
        raise ValidationError(f'{label} has no host.')
    if host.lower() in _allowlist(allowlist_setting):
        return url
    try:
        ipaddress.ip_address(host)
        if _is_blocked_ip(host):
            raise ValidationError(f'{label} host is not a routable address.')
        return url
    except ValueError:
        pass  # hostname — resolve it
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationError(f'{label} host could not be resolved.')
    for info in infos:
        if _is_blocked_ip(info[4][0]):
            raise ValidationError(f'{label} resolves to a non-routable address.')
    return url
