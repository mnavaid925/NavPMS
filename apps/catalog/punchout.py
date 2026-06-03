"""Punch-out connector registry (Module 10, sub-module 4).

Mirrors the pluggable payment-gateway pattern in ``apps/tenants/gateways.py``: a
``Protocol`` + a ``_PUNCHOUT_REGISTRY`` + an env-selectable default. The real
cXML and OCI protocols are implemented here; a ``LoopbackConnector`` test double
lets the whole round-trip be exercised without a live supplier.

cXML round-trip (server-mediated):
  build_setup() -> POST PunchOutSetupRequest to the supplier -> parse the
  PunchOutSetupResponse <StartPage> -> redirect the browser there -> the supplier
  POSTs a PunchOutOrderMessage back to our return URL -> parse_cart().

OCI round-trip (browser-mediated):
  build_setup() returns a browser auto-POST form (HOOK_URL = our return URL) ->
  the supplier site is the start page -> it POSTs NEW_ITEM-* fields back ->
  parse_cart().

SECURITY (flagged per the project vulnerability rule):
  * SSRF — ``validate_punchout_url`` is fail-closed: HTTPS-only, blocks raw-internal
    IPs and hostnames that resolve to non-routable ranges. Applied to the configured
    setup URL (model ``clean``) and again to the supplier-returned StartPage.
  * XXE — inbound XML is parsed with :mod:`defusedxml`, never the stdlib parser.
  * The inbound cart POST is authenticated by the unguessable session return token
    (resolved in the view) AND, for cXML, the ``<SharedSecret>`` in the POOM.
"""
from __future__ import annotations

import ipaddress
import secrets
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import urlparse

import requests
from defusedxml.ElementTree import fromstring as safe_fromstring
from defusedxml.common import DefusedXmlException
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

# Outbound POST budget for the cXML setup handshake.
SETUP_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------------------
# Result value objects
# ---------------------------------------------------------------------------
@dataclass
class SetupDescriptor:
    """How to drive the buyer's browser to the supplier's start page."""
    server_post: bool                 # True: we POST then redirect; False: browser auto-form
    url: str = ''                     # endpoint (server POST target, or browser form action)
    method: str = 'POST'              # browser-form method (OCI)
    body: str = ''                    # server-POST request body (cXML)
    headers: dict = field(default_factory=dict)
    fields: dict = field(default_factory=dict)  # browser-form fields (OCI)


@dataclass
class PunchoutCart:
    ok: bool
    lines: list = field(default_factory=list)   # [{name, sku, quantity, unit_price, uom, currency}]
    message: str = ''


# ---------------------------------------------------------------------------
# SSRF guard (fail-closed)
# ---------------------------------------------------------------------------
def _allowlist():
    raw = getattr(settings, 'PUNCHOUT_SSRF_ALLOWLIST', '') or ''
    return {h.strip().lower() for h in raw.split(',') if h.strip()}


def _is_blocked_ip(ip_str):
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unpar. — treat as unsafe
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
    )


def validate_punchout_url(url):
    """Raise ``ValidationError`` unless ``url`` is a safe outbound HTTPS target.

    WARNING (SSRF): a punch-out setup URL (and the supplier-returned StartPage) is
    operator-supplied and then requested server-side. Without this guard an
    attacker could point it at ``http://169.254.169.254/`` or an internal host.
    Secure pattern: HTTPS-only, reject raw internal IP literals, and resolve
    hostnames — blocking any that map to a non-routable address. Fail closed.
    """
    parsed = urlparse((url or '').strip())
    if parsed.scheme != 'https':
        raise ValidationError('Punch-out URL must use HTTPS.')
    host = parsed.hostname
    if not host:
        raise ValidationError('Punch-out URL has no host.')

    if host.lower() in _allowlist():
        return url

    # Raw IP literal — block internal ranges outright.
    try:
        ipaddress.ip_address(host)
        if _is_blocked_ip(host):
            raise ValidationError('Punch-out URL host is not a routable address.')
        return url
    except ValueError:
        pass  # it's a hostname — resolve it

    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationError('Punch-out URL host could not be resolved.')
    for info in infos:
        if _is_blocked_ip(info[4][0]):
            raise ValidationError('Punch-out URL resolves to a non-routable address.')
    return url


def _http_post(url, body, headers):
    """Server-side POST for the cXML setup handshake (no redirects, timed out)."""
    return requests.post(
        url, data=body.encode('utf-8'), headers=headers,
        timeout=SETUP_TIMEOUT_SECONDS, allow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Connector protocol
# ---------------------------------------------------------------------------
class PunchoutConnector(Protocol):
    name: str

    def build_setup(self, *, config, session, return_url) -> SetupDescriptor: ...
    def parse_setup_response(self, text: str) -> str: ...
    def authenticate_inbound(self, *, request, config, session) -> bool: ...
    def parse_cart(self, *, request, config, session) -> PunchoutCart: ...


def _money(value):
    try:
        return Decimal(str(value or '0')).quantize(Decimal('0.0001'))
    except (InvalidOperation, ValueError):
        return Decimal('0.0000')


# ---------------------------------------------------------------------------
# cXML
# ---------------------------------------------------------------------------
class CxmlConnector:
    name = 'cxml'

    def build_setup(self, *, config, session, return_url):
        ts = timezone.now().isoformat()
        payload_id = f'{secrets.token_hex(8)}@navpms'
        cxml = ET.Element('cXML', {'payloadID': payload_id, 'timestamp': ts})
        header = ET.SubElement(cxml, 'Header')

        def _cred(parent, tag, domain, identity, secret=None):
            wrap = ET.SubElement(parent, tag)
            cred = ET.SubElement(wrap, 'Credential', {'domain': domain})
            ET.SubElement(cred, 'Identity').text = identity or ''
            if secret is not None:
                ET.SubElement(cred, 'SharedSecret').text = secret

        _cred(header, 'From', 'NetworkID', config.from_identity)
        _cred(header, 'To', 'DUNS', config.to_identity)
        _cred(header, 'Sender', 'NetworkID', config.sender_identity,
              secret=config.shared_secret or '')
        sender = header.find('Sender')
        ET.SubElement(sender, 'UserAgent').text = 'NavPMS PunchOut'

        request = ET.SubElement(cxml, 'Request')
        posr = ET.SubElement(request, 'PunchOutSetupRequest', {'operation': 'create'})
        ET.SubElement(posr, 'BuyerCookie').text = session.buyer_cookie
        bfp = ET.SubElement(posr, 'BrowserFormPost')
        ET.SubElement(bfp, 'URL').text = return_url
        ss = ET.SubElement(posr, 'SupplierSetup')
        ET.SubElement(ss, 'URL').text = config.setup_url

        body = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
            cxml, encoding='unicode')
        return SetupDescriptor(
            server_post=True, url=config.setup_url, body=body,
            headers={'Content-Type': 'text/xml; charset=utf-8'},
        )

    def parse_setup_response(self, text):
        try:
            root = safe_fromstring(text or '')
        except (DefusedXmlException, ET.ParseError):
            return ''
        sp = root.find('.//PunchOutSetupResponse/StartPage/URL')
        return (sp.text or '').strip() if sp is not None else ''

    def _inbound_root(self, request):
        raw = request.POST.get('cxml-urlencoded') or request.body
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8', 'replace')
        return safe_fromstring(raw)

    def authenticate_inbound(self, *, request, config, session):
        try:
            root = self._inbound_root(request)
        except (DefusedXmlException, ET.ParseError):
            return False
        sender_secret = root.find('.//Header/Sender/Credential/SharedSecret')
        presented = (sender_secret.text or '').strip() if sender_secret is not None else ''
        # Constant-time compare; if no secret is configured, fall back to the token.
        if not config.shared_secret:
            return True
        return secrets.compare_digest(presented, config.shared_secret)

    def parse_cart(self, *, request, config, session):
        try:
            root = self._inbound_root(request)
        except (DefusedXmlException, ET.ParseError) as exc:
            return PunchoutCart(ok=False, message=f'Malformed cXML: {exc}')
        lines = []
        for item in root.iter('ItemIn'):
            qty = item.get('quantity') or '1'
            detail = item.find('ItemDetail')
            item_id = item.find('ItemID/SupplierPartID')
            desc = detail.find('Description') if detail is not None else None
            price = detail.find('UnitPrice/Money') if detail is not None else None
            uom = detail.find('UnitOfMeasure') if detail is not None else None
            lines.append({
                'name': (getattr(desc, 'text', '') or '').strip()[:200] or 'Punch-out item',
                'sku': (getattr(item_id, 'text', '') or '').strip()[:60],
                'quantity': _qty(qty),
                'unit_price': _money(getattr(price, 'text', '0')),
                'currency': (price.get('currency') if price is not None else '') or 'USD',
                'uom': (getattr(uom, 'text', '') or 'each').strip()[:12].lower() or 'each',
            })
        return PunchoutCart(ok=True, lines=lines)


# ---------------------------------------------------------------------------
# OCI (SAP Open Catalog Interface)
# ---------------------------------------------------------------------------
class OciConnector:
    name = 'oci'

    def build_setup(self, *, config, session, return_url):
        fields = {
            'HOOK_URL': return_url,
            '~OkCode': 'ADDI',
            '~OCI_SESSION': session.buyer_cookie,
        }
        if config.username:
            fields['USERNAME'] = config.username
        if config.shared_secret:
            fields['PASSWORD'] = config.shared_secret
        if isinstance(config.extra_params, dict):
            fields.update({str(k): str(v) for k, v in config.extra_params.items()})
        return SetupDescriptor(
            server_post=False, url=config.setup_url, method='POST', fields=fields,
        )

    def parse_setup_response(self, text):
        return ''  # OCI has no server setup response

    def authenticate_inbound(self, *, request, config, session):
        # OCI carries no shared secret on the return; the unguessable return token
        # resolved by the view is the authenticator. Optionally echo-check the session.
        echoed = request.POST.get('~OCI_SESSION') or request.POST.get('OCI_SESSION')
        if echoed:
            return secrets.compare_digest(echoed, session.buyer_cookie)
        return True

    def parse_cart(self, *, request, config, session):
        post = request.POST
        lines = []
        index = 1
        # OCI fields are NEW_ITEM-DESCRIPTION[1], NEW_ITEM-QUANTITY[1], ...
        while True:
            desc = post.get(f'NEW_ITEM-DESCRIPTION[{index}]')
            if desc is None and index > 1:
                break
            if desc is None:
                index += 1
                if index > 200:
                    break
                continue
            lines.append({
                'name': desc.strip()[:200] or 'Punch-out item',
                'sku': (post.get(f'NEW_ITEM-VENDORMAT[{index}]', '') or '').strip()[:60],
                'quantity': _qty(post.get(f'NEW_ITEM-QUANTITY[{index}]', '1')),
                'unit_price': _money(post.get(f'NEW_ITEM-PRICE[{index}]', '0')),
                'currency': (post.get(f'NEW_ITEM-CURRENCY[{index}]', '') or 'USD').strip()[:3],
                'uom': (post.get(f'NEW_ITEM-UNIT[{index}]', 'each') or 'each').strip()[:12].lower(),
            })
            index += 1
            if index > 200:
                break
        return PunchoutCart(ok=True, lines=lines)


# ---------------------------------------------------------------------------
# Loopback (test double — no network, deterministic)
# ---------------------------------------------------------------------------
class LoopbackConnector:
    """Drives the whole flow locally. The 'supplier' simply posts back to us.

    Inbound cart is read from simple POST fields so tests control it directly:
      shared_secret, and repeated item_name/item_qty/item_price/item_sku/item_uom.
    """
    name = 'loopback'

    def build_setup(self, *, config, session, return_url):
        return SetupDescriptor(
            server_post=False, url=return_url, method='POST',
            fields={'buyer_cookie': session.buyer_cookie},
        )

    def parse_setup_response(self, text):
        return ''

    def authenticate_inbound(self, *, request, config, session):
        if not config.shared_secret:
            return True
        presented = request.POST.get('shared_secret', '')
        return secrets.compare_digest(presented, config.shared_secret)

    def parse_cart(self, *, request, config, session):
        post = request.POST
        names = post.getlist('item_name')
        qtys = post.getlist('item_qty')
        prices = post.getlist('item_price')
        skus = post.getlist('item_sku')
        uoms = post.getlist('item_uom')
        lines = []
        for i, name in enumerate(names):
            lines.append({
                'name': name.strip()[:200] or 'Punch-out item',
                'sku': (skus[i] if i < len(skus) else '').strip()[:60],
                'quantity': _qty(qtys[i] if i < len(qtys) else '1'),
                'unit_price': _money(prices[i] if i < len(prices) else '0'),
                'currency': 'USD',
                'uom': (uoms[i] if i < len(uoms) else 'each').strip()[:12].lower() or 'each',
            })
        return PunchoutCart(ok=True, lines=lines)


def _qty(value):
    try:
        q = Decimal(str(value or '1')).quantize(Decimal('0.01'))
        return q if q > 0 else Decimal('1.00')
    except (InvalidOperation, ValueError):
        return Decimal('1.00')


_PUNCHOUT_REGISTRY = {
    'cxml': CxmlConnector,
    'oci': OciConnector,
    'loopback': LoopbackConnector,
}


def get_connector(config=None):
    """Return the connector for ``config.protocol`` (or the env default)."""
    name = getattr(config, 'protocol', None) or getattr(
        settings, 'PUNCHOUT_CONNECTOR', 'cxml')
    cls = _PUNCHOUT_REGISTRY.get(name, CxmlConnector)
    return cls()
