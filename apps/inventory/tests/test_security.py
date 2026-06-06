"""Module 19 security tests: cross-tenant isolation (IDOR), RBAC gating, negative-stock guard."""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventory import services

from .conftest import make_stock

pytestmark = pytest.mark.django_db


def test_cross_tenant_stock_detail_is_404(client, data, tenant_admin, intruder):
    """An admin of another tenant must not see this tenant's stock item (D-02)."""
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '10', tenant_admin)
    client.force_login(intruder)
    resp = client.get(reverse('inventory:stock_item_detail', args=[si.pk]))
    assert resp.status_code == 404


def test_cross_tenant_warehouse_is_404(client, data, intruder):
    client.force_login(intruder)
    resp = client.get(reverse('inventory:warehouse_detail', args=[data.wh.pk]))
    assert resp.status_code == 404


def test_cross_tenant_adjust_is_404(client, data, tenant_admin, intruder):
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '10', tenant_admin)
    client.force_login(intruder)
    resp = client.post(reverse('inventory:stock_item_adjust', args=[si.pk]),
                       {'warehouse': data.wh.pk, 'quantity': '5'})
    assert resp.status_code == 404
    si.refresh_from_db()
    assert si.quantity_on_hand == Decimal('10.00')  # untouched


def test_approver_can_view_cannot_manage(client, data, approver):
    client.force_login(approver)
    # View allowed.
    assert client.get(reverse('inventory:stock_list')).status_code == 200
    # Manage bounced (redirect, no warehouse created).
    resp = client.post(reverse('inventory:warehouse_create'),
                       {'code': 'NOPE', 'name': 'x', 'is_active': 'on'})
    assert resp.status_code == 302
    from apps.inventory.models import Warehouse
    assert not Warehouse.objects.filter(tenant=data.tenant, code='NOPE').exists()


def test_requester_cannot_view(client, data, requester):
    client.force_login(requester)
    assert client.get(reverse('inventory:movement_list')).status_code == 302
    assert client.get(reverse('inventory:goods_issue_list')).status_code == 302


def test_negative_stock_guard_service(data, tenant_admin):
    from django.core.exceptions import ValidationError
    si = make_stock(data.tenant, data.ci, data.wh, data.loc, '3', tenant_admin)
    with pytest.raises(ValidationError):
        services.apply_movement(
            tenant=data.tenant, stock_item=si, warehouse=data.wh, location=data.loc,
            movement_type='issue', quantity=Decimal('-5'), actor=tenant_admin)
