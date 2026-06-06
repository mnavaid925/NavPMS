"""Tamper-evident audit hash-chain tests (Module 18, sub-module 3 — lives on apps.tenants.AuditLog)."""
import pytest

from apps.core.models import Tenant, set_current_tenant
from apps.tenants.models import AuditLog
from apps.tenants.services import record_audit, verify_audit_chain

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_tenant():
    yield
    set_current_tenant(None)


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(name='Acme', slug='acme')


def test_record_audit_builds_a_linked_chain(tenant):
    a = record_audit(tenant, None, 'compliance.x', message='one')
    b = record_audit(tenant, None, 'compliance.y', message='two')
    c = record_audit(tenant, None, 'compliance.z', message='three')
    assert a.prev_hash == ''            # genesis
    assert a.row_hash and b.row_hash and c.row_hash
    assert b.prev_hash == a.row_hash    # each links to the prior row
    assert c.prev_hash == b.row_hash


def test_verify_passes_on_an_untampered_chain(tenant):
    for i in range(5):
        record_audit(tenant, None, 'compliance.evt', message=f'event {i}')
    result = verify_audit_chain(tenant)
    assert result['ok'] is True
    assert result['checked'] == 5
    assert result['first_broken_id'] is None


def test_verify_detects_a_tampered_row(tenant):
    rows = [record_audit(tenant, None, 'compliance.evt', message=f'event {i}') for i in range(5)]
    victim = rows[2]
    # Tamper directly in the DB, bypassing record_audit (which would re-chain) — simulates an
    # attacker editing a historic log row.
    AuditLog.all_objects.filter(pk=victim.pk).update(message='ALTERED')
    result = verify_audit_chain(tenant)
    assert result['ok'] is False
    assert result['first_broken_id'] == victim.pk


def test_verify_detects_a_deleted_row(tenant):
    rows = [record_audit(tenant, None, 'compliance.evt', message=f'event {i}') for i in range(5)]
    # Deleting a middle row breaks the prev_hash link of the row that followed it.
    AuditLog.all_objects.filter(pk=rows[2].pk).delete()
    result = verify_audit_chain(tenant)
    assert result['ok'] is False
    assert result['first_broken_id'] == rows[3].pk


def test_chain_is_per_tenant(tenant):
    other = Tenant.objects.create(name='Globex', slug='globex')
    record_audit(tenant, None, 'a', message='t1')
    record_audit(other, None, 'b', message='t2')
    record_audit(tenant, None, 'c', message='t1b')
    assert verify_audit_chain(tenant)['ok'] is True
    assert verify_audit_chain(other)['ok'] is True
