"""Model tests for Module 10: numbering, status helpers, price resolution proxy,
tier currency window, append-only timeline and uniqueness constraints."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import (
    CatalogItem,
    CatalogItemStatusEvent,
    CatalogPriceChangeRequest,
    CatalogPriceTier,
)
from apps.catalog.services import next_item_number
from apps.core.models import set_current_tenant

pytestmark = pytest.mark.django_db


class TestNumbering:
    def test_number_format(self, tenant, draft_item):
        assert draft_item.item_number.startswith('CAT-ACME-')

    def test_number_increments(self, tenant, tenant_admin):
        set_current_tenant(tenant)
        CatalogItem.all_objects.create(
            tenant=tenant, item_number='CAT-ACME-00007', name='X',
            base_price=Decimal('1'), created_by=tenant_admin)
        assert next_item_number(tenant) == 'CAT-ACME-00008'


class TestItemProperties:
    def test_status_flags(self, draft_item, approved_item, rejected_item):
        assert draft_item.is_editable and draft_item.can_submit
        assert not draft_item.is_approved
        assert approved_item.is_approved and approved_item.is_orderable
        assert approved_item.can_retire and not approved_item.is_editable
        assert rejected_item.is_editable  # rejected returns to editable

    def test_effective_price_uses_tiers(self, approved_item):
        # base 12.50; tiers at 10→11.00 and 50→9.75; min_order_qty 1 → base.
        assert approved_item.effective_price == Decimal('12.5000')


class TestPriceResolution:
    def test_base_when_no_tier(self, draft_item):
        from apps.catalog.services import resolve_price
        assert resolve_price(draft_item, qty=Decimal('1')) == draft_item.base_price

    def test_volume_break(self, approved_item):
        from apps.catalog.services import resolve_price
        assert resolve_price(approved_item, qty=Decimal('10')) == Decimal('11.0000')
        assert resolve_price(approved_item, qty=Decimal('60')) == Decimal('9.7500')

    def test_future_tier_not_current(self, tenant, draft_item):
        set_current_tenant(tenant)
        from apps.catalog.services import resolve_price
        future = timezone.localdate() + timedelta(days=30)
        CatalogPriceTier.all_objects.create(
            tenant=tenant, item=draft_item, tier_type='volume',
            min_quantity=Decimal('1'), unit_price=Decimal('1.0000'),
            effective_from=future)
        # The future tier is not yet current → falls back to base.
        assert resolve_price(draft_item, qty=Decimal('100')) == draft_item.base_price


class TestTier:
    def test_is_current_window(self, tenant, draft_item):
        set_current_tenant(tenant)
        today = timezone.localdate()
        t = CatalogPriceTier.all_objects.create(
            tenant=tenant, item=draft_item, tier_type='volume',
            min_quantity=Decimal('1'), unit_price=Decimal('5'),
            effective_from=today - timedelta(days=1),
            effective_to=today + timedelta(days=1))
        assert t.is_current
        t.effective_to = today - timedelta(days=1)
        assert not t.is_current


class TestTimeline:
    def test_status_events_recorded(self, approved_item):
        statuses = list(CatalogItemStatusEvent.all_objects.filter(
            item=approved_item).values_list('status', flat=True))
        # The fixture builds the row directly then runs the real submit/approve
        # services, so the lifecycle transitions are recorded on the timeline.
        assert 'pending_approval' in statuses and 'approved' in statuses

    def test_create_item_records_draft_event(self, tenant, tenant_admin):
        set_current_tenant(tenant)
        from apps.catalog.services import create_item
        item = create_item(tenant=tenant, user=tenant_admin, name='Fresh',
                            base_price=Decimal('1'))
        assert CatalogItemStatusEvent.all_objects.filter(
            item=item, status='draft').exists()


class TestConstraints:
    def test_item_number_unique_per_tenant(self, tenant, tenant_admin, draft_item):
        set_current_tenant(tenant)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CatalogItem.all_objects.create(
                    tenant=tenant, item_number=draft_item.item_number,
                    name='dupe', base_price=Decimal('1'), created_by=tenant_admin)

    def test_price_change_number_unique_per_item(self, tenant, approved_item):
        set_current_tenant(tenant)
        CatalogPriceChangeRequest.all_objects.create(
            tenant=tenant, item=approved_item, request_number='X-PC01',
            change_type='base', new_base_price=Decimal('1'))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CatalogPriceChangeRequest.all_objects.create(
                    tenant=tenant, item=approved_item, request_number='X-PC01',
                    change_type='base', new_base_price=Decimal('2'))
