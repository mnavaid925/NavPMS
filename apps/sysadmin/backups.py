"""Module 21 — pluggable backup connector + ``run_backup`` orchestration (sub-module 4).

Mock by default: ``MockBackupConnector.perform`` does no real I/O — it computes a deterministic
synthetic size + SHA-256 manifest checksum from the tenant's row counts, so the backup history,
dashboards and tests populate with believable data and zero external dependencies. A real connector
(pg_dump → S3, etc.) registers in ``_REGISTRY`` and is selected via ``settings.BACKUP_CONNECTOR``.

``run_backup`` is the audited orchestration: it mints a gap-free ``BKR-<SLUG>-NNNNN`` run number,
creates the :class:`BackupRun` row, invokes the connector, records the outcome, stamps the policy's
``last_run_at`` and writes a ``tenants.AuditLog`` entry. Restore is intentionally NOT executed here —
:class:`RestoreRequest` is a logged approval protocol, never a live overwrite.
"""
import hashlib
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.tenants.services import record_audit

from .models import BackupRun


@dataclass
class BackupResult:
    ok: bool = True
    size_bytes: int = 0
    location: str = ''
    checksum: str = ''
    message: str = ''
    connector: str = 'mock'


class BackupConnector:
    """Connector protocol. Real backends override ``perform``."""

    name = 'base'

    def perform(self, tenant, scope, *, policy=None):  # pragma: no cover - overridden
        raise NotImplementedError


class MockBackupConnector(BackupConnector):
    """Network-free connector that fabricates a believable, deterministic backup artefact."""

    name = 'mock'

    def perform(self, tenant, scope, *, policy=None):
        # Deterministic "size" derived from how much data the tenant holds, so it is stable per run
        # input but varies across tenants/scopes — no randomness (keeps tests/seed reproducible).
        from apps.accounts.models import User
        users = User.objects.filter(tenant=tenant).count()
        seed = f'{tenant.slug}:{scope}:{users}'
        digest = hashlib.sha256(seed.encode('utf-8')).hexdigest()
        base_mb = {'full': 48, 'db_only': 22, 'media_only': 30}.get(scope, 40)
        size_bytes = (base_mb + users * 3 + (int(digest[:4], 16) % 16)) * 1024 * 1024
        target = (policy.storage_target if policy else 'local')
        location = f'{target}://navpms-backups/{tenant.slug}/{scope}-{digest[:12]}.tar.gz'
        return BackupResult(
            ok=True, size_bytes=size_bytes, location=location, checksum=digest,
            message=f'Mock {scope} backup completed.', connector='mock')


_REGISTRY = {
    'mock': MockBackupConnector(),
}


def register_backup_connector(connector):
    _REGISTRY[connector.name] = connector


def get_backup_connector(name=None):
    key = (name or getattr(settings, 'BACKUP_CONNECTOR', 'mock') or 'mock').lower()
    return _REGISTRY.get(key) or _REGISTRY['mock']


@transaction.atomic
def run_backup(tenant, *, policy=None, trigger='manual', scope=None, user=None, request=None,
               connector=None):
    """Execute a backup (via the pluggable connector) and record an audited :class:`BackupRun`."""
    from .services import next_backup_run_number  # local import avoids an import cycle

    scope = scope or (policy.scope if policy else 'full')
    started = timezone.now()
    run = BackupRun.all_objects.create(
        tenant=tenant, run_number=next_backup_run_number(tenant), policy=policy,
        status='running', trigger=trigger, scope=scope, started_at=started)
    conn = connector or get_backup_connector()
    try:
        result = conn.perform(tenant, scope, policy=policy)
    except Exception as exc:  # a real connector may raise — never let it crash the request
        result = BackupResult(ok=False, message=str(exc)[:255], connector=getattr(conn, 'name', ''))
    finished = timezone.now()
    run.status = 'success' if result.ok else 'failed'
    run.finished_at = finished
    run.size_bytes = result.size_bytes
    run.location = result.location
    run.checksum = result.checksum
    run.connector = result.connector
    run.message = result.message[:255]
    run.save(update_fields=['status', 'finished_at', 'size_bytes', 'location', 'checksum',
                            'connector', 'message', 'updated_at'])
    if policy is not None:
        policy.last_run_at = finished
        policy.save(update_fields=['last_run_at', 'updated_at'])
    record_audit(
        tenant, user, 'sysadmin.backup_run', level='info' if result.ok else 'warning',
        target_type='BackupRun', target_id=str(run.pk),
        message=f'Backup {run.run_number} {run.status} ({run.size_mb} MB).', request=request)
    return run


def prune_expired_runs(tenant, *, policy=None, now=None):
    """Delete BackupRun rows older than their policy's retention window. Returns the count removed."""
    now = now or timezone.now()
    qs = BackupRun.all_objects.filter(tenant=tenant, status='success')
    if policy is not None:
        from datetime import timedelta
        cutoff = now - timedelta(days=policy.retention_days)
        qs = qs.filter(policy=policy, created_at__lt=cutoff)
        removed = qs.count()
        qs.delete()
        return removed
    # No policy: prune each policy's runs by its own retention.
    from datetime import timedelta
    removed = 0
    seen = set()
    for run in BackupRun.all_objects.filter(tenant=tenant).select_related('policy'):
        pol = run.policy
        if not pol or pol.pk in seen:
            continue
        seen.add(pol.pk)
        cutoff = now - timedelta(days=pol.retention_days)
        old = BackupRun.all_objects.filter(
            tenant=tenant, policy=pol, status='success', created_at__lt=cutoff)
        removed += old.count()
        old.delete()
    return removed
