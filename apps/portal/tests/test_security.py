"""Security regression tests — OWASP-mapped.

Each test pins a fix from the §6 defect register of .claude/Test.md so a
regression re-opens as a red test.
"""
import pytest
from django.urls import reverse

from apps.portal.forms import NotificationForm, QuickRequisitionItemForm
from apps.portal.models import Notification

pytestmark = pytest.mark.django_db


# ---------- A04 — Insecure design (D-01) ----------

def test_A04_item_form_rejects_negative_values():
    form = QuickRequisitionItemForm(
        {'name': 'X', 'quantity': '-5', 'unit': 'u', 'unit_price': '-10'})
    assert not form.is_valid()
    assert 'quantity' in form.errors and 'unit_price' in form.errors


def test_A04_item_form_rejects_zero_quantity():
    form = QuickRequisitionItemForm(
        {'name': 'X', 'quantity': '0', 'unit': 'u', 'unit_price': '5'})
    assert not form.is_valid() and 'quantity' in form.errors


def test_A04_item_form_accepts_valid_values():
    form = QuickRequisitionItemForm(
        {'name': 'X', 'quantity': '2.5', 'unit': 'u', 'unit_price': '0'})
    assert form.is_valid()


# ---------- A03 — Injection / XSS (D-02) ----------

@pytest.mark.parametrize('bad', [
    'javascript:alert(1)', 'JavaScript:alert(1)',
    'data:text/html,<script>', 'vbscript:msgbox(1)',
])
def test_A03_notification_rejects_script_scheme(bad):
    form = NotificationForm({
        'category': 'info', 'priority': 'normal', 'title': 'T',
        'message': 'm', 'link_url': bad})
    assert not form.is_valid() and 'link_url' in form.errors


@pytest.mark.parametrize('ok', [
    '/portal/requisitions/', 'https://example.com/x',
    'http://example.com', '', '#section',
])
def test_A03_notification_accepts_safe_url(ok):
    form = NotificationForm({
        'category': 'info', 'priority': 'normal', 'title': 'T',
        'message': 'm', 'link_url': ok})
    assert form.is_valid(), form.errors


# ---------- A01 — Broken access control (D-03) ----------

def test_A01_toggle_read_rejects_external_redirect(client_logged_in, notification):
    resp = client_logged_in.post(
        reverse('portal:notification_mark_read', args=[notification.pk]),
        {'next': 'https://evil.example/phish'})
    assert 'evil.example' not in resp['Location']
    assert resp['Location'] == reverse('portal:notification_list')


def test_A01_toggle_read_allows_same_site_next(client_logged_in, notification):
    safe = reverse('portal:notification_detail', args=[notification.pk])
    resp = client_logged_in.post(
        reverse('portal:notification_mark_read', args=[notification.pk]),
        {'next': safe})
    assert resp['Location'] == safe


def test_A01_anonymous_redirected_to_login(client):
    resp = client.get(reverse('portal:dashboard'))
    assert resp.status_code == 302 and 'login' in resp['Location'].lower()


def test_A01_tenantless_user_redirected(client, db):
    """A logged-in user with no tenant cannot reach the portal."""
    from apps.accounts.models import User
    nomad = User.objects.create_user(
        username='nomad', password='x', tenant=None)
    client.force_login(nomad)
    resp = client.get(reverse('portal:dashboard'))
    assert resp.status_code == 302
    assert reverse('portal:dashboard') not in resp['Location']


# ---------- A03 — CSRF ----------

def test_A03_csrf_enforced_on_post(csrf_client):
    resp = csrf_client.post(reverse('portal:notification_create'), {
        'category': 'info', 'priority': 'normal', 'title': 'No token'})
    assert resp.status_code == 403
    assert not Notification.all_objects.filter(title='No token').exists()
