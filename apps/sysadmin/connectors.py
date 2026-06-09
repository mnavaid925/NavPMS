"""Module 21 — pluggable SSO / LDAP connector registry (sub-module 2).

Mock by default (works with zero external deps, fully demoable). A real SAML / OIDC / LDAP backend
registers itself in ``_REGISTRY`` and is selected per-provider via ``IdentityProvider.connector`` or
globally via ``settings.SSO_CONNECTOR`` — exactly the pattern used by ``apps/compliance/screening.py``
and ``apps/catalog/punchout.py``.

The mock connector performs no network I/O: ``test_connection`` sanity-checks the stored config and
``simulate_login`` deterministically "authenticates" an email so the UI, seed data and tests all work
out of the box. ``validate_metadata_url`` reuses the shared fail-closed SSRF guard.
"""
from dataclasses import dataclass, field

from django.conf import settings

from .validators import validate_outbound_url


def validate_metadata_url(url):
    """SSRF-guard an SSO metadata URL (HTTPS + public-host only, allowlist via SSO_METADATA_ALLOWLIST)."""
    return validate_outbound_url(
        url, allowlist_setting='SSO_METADATA_ALLOWLIST', label='Metadata URL')


@dataclass
class SSOResult:
    ok: bool = True
    outcome: str = 'success'          # success / failed / provisioned
    subject_id: str = ''
    email: str = ''
    message: str = ''
    attributes: dict = field(default_factory=dict)
    connector: str = 'mock'


class SSOConnector:
    """Connector protocol. Real backends override ``test_connection`` / ``authenticate``."""

    name = 'base'

    def test_connection(self, provider):  # pragma: no cover - overridden
        raise NotImplementedError

    def authenticate(self, provider, email, **kwargs):  # pragma: no cover - overridden
        raise NotImplementedError


class MockSSOConnector(SSOConnector):
    """Deterministic, network-free connector for local/dev/test."""

    name = 'mock'

    def test_connection(self, provider):
        problems = []
        if provider.protocol in ('saml', 'oidc'):
            if not (provider.sso_url or provider.metadata_url):
                problems.append('Missing sign-in / metadata URL.')
            if not provider.entity_id:
                problems.append('Missing entity ID / issuer.')
        elif provider.protocol == 'ldap':
            if not provider.server_uri:
                problems.append('Missing LDAP server URI.')
            if not provider.bind_dn:
                problems.append('Missing bind DN.')
        if problems:
            return SSOResult(ok=False, outcome='failed', message=' '.join(problems), connector='mock')
        return SSOResult(
            ok=True, outcome='success', connector='mock',
            message=f'Mock {provider.protocol.upper()} connection looks valid.')

    def authenticate(self, provider, email, **kwargs):
        email = (email or '').strip().lower()
        if not email:
            return SSOResult(ok=False, outcome='failed', message='No email supplied.', connector='mock')
        domains = [d.strip().lower() for d in (provider.allowed_domains or '').split(',') if d.strip()]
        if domains and email.split('@')[-1] not in domains:
            return SSOResult(
                ok=False, outcome='failed', email=email, connector='mock',
                message=f'Domain not permitted for {provider.name}.')
        local = email.split('@')[0]
        return SSOResult(
            ok=True, outcome='success', email=email, subject_id=f'mock|{local}', connector='mock',
            message='Mock authentication succeeded.',
            attributes={'email': email, 'first_name': local.split('.')[0].title()})


_REGISTRY = {
    'mock': MockSSOConnector(),
}


def register_sso_connector(connector):
    """Register a real connector instance (call from app ready() of a plugin)."""
    _REGISTRY[connector.name] = connector


def get_sso_connector(name=None):
    """Resolve a connector by name (falls back to the configured default, then ``mock``)."""
    key = (name or getattr(settings, 'SSO_CONNECTOR', 'mock') or 'mock').lower()
    return _REGISTRY.get(key) or _REGISTRY['mock']
