"""Shared fixtures for Module 8 (E-Auction Management) tests.

Mirrors the layout/style of ``apps/rfx/tests/conftest.py``: tenants & users,
vendors, then auction fixtures.

IMPORTANT (per lessons.md): every auction fixture CREATES its own row — we never
build ``live_auction`` by mutating ``draft_auction`` in place (that would poison
status-filter tests). Auction-creating fixtures call ``set_current_tenant`` first
so the tenant-aware/denorm path is bound, then use the real services
(``invite_vendors`` / ``publish``/``start`` / ``place_bid``) to keep the seeded
state honest.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import Tenant, set_current_tenant
from apps.auctions.models import Auction, AuctionLot
from apps.auctions.services import (
    accept_invitation, close_auction, finalize_auction, invite_vendors,
    place_bid, publish_auction, start_auction,
)
from apps.vendors.models import Vendor


# ---------- Tenants & users ----------

@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme Co', slug='acme')


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(name='Globex', slug='globex')


@pytest.fixture
def tenant_admin(db, tenant):
    return User.objects.create_user(
        username='admin_acme', password='x', tenant=tenant,
        role='tenant_admin', is_tenant_admin=True,
    )


@pytest.fixture
def buyer_user(db, tenant):
    return User.objects.create_user(
        username='buyer', password='x', tenant=tenant, role='buyer',
    )


@pytest.fixture
def procurement_manager(db, tenant):
    """Manage-role user WITHOUT is_tenant_admin, so the MANAGE_ROLES membership
    branch of can_manage_auction is exercised (not the is_tenant_admin
    short-circuit)."""
    return User.objects.create_user(
        username='pmgr', password='x', tenant=tenant,
        role='procurement_manager',
    )


@pytest.fixture
def approver(db, tenant):
    """Monitor-only role: may view console/results but not manage."""
    return User.objects.create_user(
        username='approver_user', password='x', tenant=tenant, role='approver',
    )


# Alias mirroring the rfx fixture name for symmetry in shared tests.
@pytest.fixture
def evaluator(approver):
    return approver


@pytest.fixture
def requester(db, tenant):
    """Neither manage nor monitor."""
    return User.objects.create_user(
        username='requester', password='x', tenant=tenant, role='requester',
    )


@pytest.fixture
def intruder(db, other_tenant):
    """Tenant admin of a DIFFERENT tenant — used for cross-tenant isolation."""
    return User.objects.create_user(
        username='mallory', password='x', tenant=other_tenant,
        role='tenant_admin', is_tenant_admin=True,
    )


# ---------- Vendors ----------

@pytest.fixture
def vendor_a(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00001',
        legal_name='Acme IT Solutions', status='active',
    )


@pytest.fixture
def vendor_b(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00002',
        legal_name='Beacon Cleaners', status='active',
    )


@pytest.fixture
def vendor_c(db, tenant):
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-00003',
        legal_name='Cosmic Stationery', status='active',
    )


@pytest.fixture
def blocked_vendor(db, tenant):
    """Blacklisted vendor — invite_vendors must skip this one."""
    return Vendor.all_objects.create(
        tenant=tenant, vendor_number='VND-ACME-09999',
        legal_name='Blocked Co', status='blacklisted',
    )


@pytest.fixture
def vendor_portal_user(db, tenant, vendor_a):
    """Vendor-portal login bound to vendor_a."""
    return User.objects.create_user(
        username='portal_a', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_a,
    )


@pytest.fixture
def vendor_b_portal_user(db, tenant, vendor_b):
    """A second vendor-portal login (vendor_b) for cross-vendor leak tests."""
    return User.objects.create_user(
        username='portal_b', password='x', tenant=tenant,
        role='vendor_portal', vendor=vendor_b,
    )


# ---------- Auctions ----------
#
# Each fixture CREATES its own Auction row (never mutates a shared one). The
# common header config is: starting_price 1000, amount decrement of 50,
# reserve 800.

def _make_auction(tenant, created_by, *, status='draft', start_at=None,
                  end_at=None, number='AUC-ACME-00001'):
    """Helper: create a stand-alone auction row with the standard config."""
    return Auction.all_objects.create(
        tenant=tenant,
        auction_number=number,
        title='Office supplies reverse auction',
        auction_type='reverse',
        currency='USD',
        starting_price=Decimal('1000.00'),
        reserve_price=Decimal('800.00'),
        decrement_type='amount',
        decrement_value=Decimal('50.00'),
        status=status,
        start_at=start_at,
        end_at=end_at,
        created_by=created_by,
    )


def _add_lot(tenant, auction, *, lot_no=1):
    return AuctionLot.all_objects.create(
        tenant=tenant, auction=auction, lot_no=lot_no,
        title='Copy paper', item_description='A4 80gsm copy paper',
        uom='BOX', quantity=Decimal('100.000'),
        est_unit_price=Decimal('10.00'),
    )


@pytest.fixture
def draft_auction(db, tenant, tenant_admin):
    """A bare draft auction (no lots, no participants)."""
    set_current_tenant(tenant)
    return _make_auction(
        tenant, tenant_admin, status='draft', number='AUC-ACME-00001',
    )


@pytest.fixture
def draft_auction_ready(db, tenant, tenant_admin, vendor_a):
    """A draft with one lot + a future window + one invited vendor — ready to
    publish (validate_auction_for_publish passes)."""
    set_current_tenant(tenant)
    now = timezone.now()
    auction = _make_auction(
        tenant, tenant_admin, status='draft',
        start_at=now + timedelta(hours=1),
        end_at=now + timedelta(hours=2),
        number='AUC-ACME-00002',
    )
    _add_lot(tenant, auction)
    invite_vendors(auction, [vendor_a.pk], tenant_admin)
    return auction


@pytest.fixture
def scheduled_auction(db, tenant, tenant_admin, vendor_a, vendor_b):
    """Own object: future window, one lot, vendor_a + vendor_b invited, status
    scheduled (published but not yet started)."""
    set_current_tenant(tenant)
    now = timezone.now()
    auction = _make_auction(
        tenant, tenant_admin, status='draft',
        start_at=now + timedelta(hours=1),
        end_at=now + timedelta(hours=2),
        number='AUC-ACME-00003',
    )
    _add_lot(tenant, auction)
    invite_vendors(auction, [vendor_a.pk, vendor_b.pk], tenant_admin)
    publish_auction(auction, tenant_admin)
    auction.refresh_from_db()
    return auction


@pytest.fixture
def live_auction(db, tenant, tenant_admin, vendor_a, vendor_b, vendor_c):
    """Own object: start_at in the PAST, end_at in the FUTURE, one lot,
    vendor_a + vendor_b + vendor_c invited AND accepted, status live — ready for
    place_bid (no past end_at to auto-close on the first bid)."""
    set_current_tenant(tenant)
    now = timezone.now()
    auction = _make_auction(
        tenant, tenant_admin, status='draft',
        start_at=now - timedelta(minutes=5),
        end_at=now + timedelta(days=1),
        number='AUC-ACME-00004',
    )
    _add_lot(tenant, auction)
    participants = invite_vendors(
        auction, [vendor_a.pk, vendor_b.pk, vendor_c.pk], tenant_admin)
    for participant in participants:
        accept_invitation(participant, tenant_admin)
    publish_auction(auction, tenant_admin)   # draft -> scheduled
    start_auction(auction, tenant_admin)      # scheduled -> live
    auction.refresh_from_db()
    return auction


@pytest.fixture
def awarded_auction(db, tenant, tenant_admin, vendor_a, vendor_b, vendor_c):
    """Own object: a few decreasing bids placed via services.place_bid while
    genuinely live (end_at far in the future so anti-snipe never fires), then
    closed and finalized. Winner = vendor_c at 780."""
    set_current_tenant(tenant)
    now = timezone.now()
    auction = _make_auction(
        tenant, tenant_admin, status='draft',
        start_at=now - timedelta(minutes=5),
        end_at=now + timedelta(days=1),
        number='AUC-ACME-00005',
    )
    _add_lot(tenant, auction)
    participants = invite_vendors(
        auction, [vendor_a.pk, vendor_b.pk, vendor_c.pk], tenant_admin)
    for participant in participants:
        accept_invitation(participant, tenant_admin)
    publish_auction(auction, tenant_admin)
    start_auction(auction, tenant_admin)
    auction.refresh_from_db()

    # Decreasing bids honouring the 50 fixed decrement against the global best.
    place_bid(auction, vendor_a, Decimal('900.00'), tenant_admin, source='manual')
    place_bid(auction, vendor_b, Decimal('840.00'), tenant_admin, source='manual')
    place_bid(auction, vendor_c, Decimal('780.00'), tenant_admin, source='manual')

    close_auction(auction, tenant_admin)
    finalize_auction(auction, tenant_admin)
    auction.refresh_from_db()
    return auction
