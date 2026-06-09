"""Module 21 — webhook signing + delivery + fan-out (sub-module 5).

The public producer API is :func:`emit_event` — any module can call
``emit_event(tenant, 'po.issued', {...})`` and every active webhook subscribed to that event gets a
signed POST (and an append-only :class:`WebhookDelivery` row). The governance-layer build wires the
*delivery* machinery, the event catalog, the test/ping action and the retry worker; it does not yet
sprinkle ``emit_event`` calls across the 20 existing modules (that is incremental, opt-in).

SECURITY: every outbound URL passes the fail-closed SSRF guard *before* any network call, and each
body is HMAC-SHA256 signed with the webhook's secret so the receiver can verify authenticity. The
network call is injectable (``poster=``) so tests stay hermetic.
"""
import hashlib
import hmac
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Webhook, WebhookDelivery
from .validators import validate_outbound_url

# Event catalog — the codes a webhook may subscribe to (grouped for the UI).
WEBHOOK_EVENTS = [
    ('requisition.created', 'Requisition created'),
    ('requisition.approved', 'Requisition approved'),
    ('po.issued', 'Purchase order issued'),
    ('po.acknowledged', 'Purchase order acknowledged'),
    ('goods_receipt.posted', 'Goods receipt posted'),
    ('invoice.submitted', 'Invoice submitted'),
    ('invoice.paid', 'Invoice paid'),
    ('contract.signed', 'Contract signed'),
    ('vendor.created', 'Vendor created'),
    ('vendor.blacklisted', 'Vendor blacklisted'),
    ('sysadmin.ping', 'Test ping'),
]
WEBHOOK_EVENT_CODES = [code for code, _ in WEBHOOK_EVENTS]
WEBHOOK_EVENT_LABELS = dict(WEBHOOK_EVENTS)


def validate_webhook_url(url):
    """SSRF-guard a webhook target URL (HTTPS + public-host only, allowlist via WEBHOOK_SSRF_ALLOWLIST)."""
    return validate_outbound_url(
        url, allowlist_setting='WEBHOOK_SSRF_ALLOWLIST', label='Webhook URL')


def sign_payload(secret, body_bytes):
    """Return the hex HMAC-SHA256 signature of ``body_bytes`` under ``secret``."""
    return hmac.new((secret or '').encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()


def _default_poster(url, body_bytes, headers, timeout):
    """Real network delivery via ``requests`` (already a project dependency)."""
    import requests
    resp = requests.post(url, data=body_bytes, headers=headers, timeout=timeout)
    return resp.status_code, (resp.text or '')[:255]


def deliver(delivery, *, poster=None):
    """Attempt one delivery, updating the :class:`WebhookDelivery` row in place. Never raises."""
    poster = poster or _default_poster
    webhook = delivery.webhook
    delivery.attempts = (delivery.attempts or 0) + 1
    body = json.dumps({
        'event': delivery.event,
        'delivery_id': delivery.pk,
        'webhook': webhook.name,
        'data': delivery.payload or {},
    }, default=str).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'NavPMS-Webhook/1.0',
        'X-NavPMS-Event': delivery.event,
        'X-NavPMS-Signature': 'sha256=' + sign_payload(webhook.secret, body),
        'X-NavPMS-Delivery': str(delivery.pk),
    }
    for key, value in (webhook.custom_headers or {}).items():
        headers[str(key)] = str(value)

    try:
        validate_webhook_url(webhook.target_url)  # fail-closed BEFORE any network call
        timeout = getattr(settings, 'WEBHOOK_TIMEOUT_SECONDS', 10)
        status_code, excerpt = poster(webhook.target_url, body, headers, timeout)
        ok = 200 <= int(status_code) < 300
        delivery.status_code = int(status_code)
        delivery.response_excerpt = excerpt
        delivery.status = 'success' if ok else 'failed'
    except ValidationError as exc:
        delivery.status = 'failed'
        delivery.status_code = 0
        delivery.response_excerpt = ('Blocked: ' + '; '.join(exc.messages))[:255]
    except Exception as exc:  # network / DNS / timeout — record, don't crash
        delivery.status = 'failed'
        delivery.status_code = 0
        delivery.response_excerpt = str(exc)[:255]

    now = timezone.now()
    if delivery.status == 'success':
        delivery.delivered_at = now
        delivery.next_retry_at = None
    else:
        max_attempts = getattr(settings, 'WEBHOOK_MAX_ATTEMPTS', 5)
        if delivery.attempts < max_attempts:
            from datetime import timedelta
            delivery.next_retry_at = now + timedelta(minutes=5 * delivery.attempts)
        else:
            delivery.next_retry_at = None
    delivery.save(update_fields=['status', 'status_code', 'attempts', 'response_excerpt',
                                 'delivered_at', 'next_retry_at', 'updated_at'])
    # Denormalise last status onto the webhook for the list view.
    webhook.last_status = delivery.status
    webhook.last_delivered_at = now
    webhook.save(update_fields=['last_status', 'last_delivered_at', 'updated_at'])
    return delivery


def emit_event(tenant, event, payload, *, poster=None, attempt=True):
    """Fan ``event`` out to every active webhook in ``tenant`` subscribed to it.

    Creates one :class:`WebhookDelivery` per subscriber and (by default) attempts delivery
    immediately. Returns the list of delivery rows. This is the API other modules call.
    """
    deliveries = []
    subs = Webhook.all_objects.filter(tenant=tenant, is_active=True)
    for webhook in subs:
        if event not in (webhook.events or []):
            continue
        delivery = WebhookDelivery.all_objects.create(
            tenant=tenant, webhook=webhook, event=event, payload=payload or {}, status='pending')
        if attempt:
            deliver(delivery, poster=poster)
        deliveries.append(delivery)
    return deliveries


def test_webhook(webhook, *, poster=None):
    """Send a single ``sysadmin.ping`` delivery to one webhook (the UI "Test" action)."""
    delivery = WebhookDelivery.all_objects.create(
        tenant=webhook.tenant, webhook=webhook, event='sysadmin.ping',
        payload={'message': 'NavPMS webhook test ping.'}, status='pending')
    return deliver(delivery, poster=poster)


def retry_pending(tenant, *, poster=None, now=None):
    """Re-attempt due failed/pending deliveries still under the attempt cap. Returns counts."""
    now = now or timezone.now()
    max_attempts = getattr(settings, 'WEBHOOK_MAX_ATTEMPTS', 5)
    due = WebhookDelivery.all_objects.filter(
        tenant=tenant, status__in=('pending', 'failed'), attempts__lt=max_attempts,
    ).select_related('webhook')
    retried = succeeded = 0
    for delivery in due:
        if delivery.next_retry_at and delivery.next_retry_at > now:
            continue
        deliver(delivery, poster=poster)
        retried += 1
        if delivery.status == 'success':
            succeeded += 1
    return {'retried': retried, 'succeeded': succeeded}
