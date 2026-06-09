"""Module 21 — permission catalog (the *what* of access control).

This is the app-defined registry of fine-grained permission codes, grouped by procurement area,
plus the default grant matrix that mirrors the project's *current* hardcoded role behaviour.

Permissions are **app data, not tenant data** — every tenant shares the same catalog — so they live
here as plain Python constants (like ``apps.dms.models`` choice constants), never a per-tenant table.
What *is* tenant data is which codes a tenant grants to each role: that is the ``RolePermission``
matrix (presence of a row = granted), seeded from :data:`DEFAULT_ROLE_GRANTS`.

The governance layer ships the catalog + the matrix + a ``services.user_has_perm(user, code)`` API,
and enforces it on this module's own pages. The 20 existing apps keep their inline role checks
untouched (zero regression risk); they can consult ``user_has_perm`` incrementally later.
"""

# ---------------------------------------------------------------------------
# Built-in roles (mirror apps.accounts.models.User.ROLE_CHOICES — kept static here to avoid an
# import cycle at module-load; the seeder cross-checks against the live choices).
# ---------------------------------------------------------------------------
BUILTIN_ROLES = [
    ('super_admin', 'Super Admin'),
    ('tenant_admin', 'Tenant Admin'),
    ('procurement_manager', 'Procurement Manager'),
    ('buyer', 'Buyer'),
    ('approver', 'Approver'),
    ('requester', 'Requester'),
    ('vendor_portal', 'Vendor Portal'),
    ('viewer', 'Viewer'),
]
BUILTIN_ROLE_CODES = [code for code, _ in BUILTIN_ROLES]

# Roles that always hold every permission regardless of the matrix (they administer it).
SUPERUSER_ROLE_CODES = ('super_admin', 'tenant_admin')


# ---------------------------------------------------------------------------
# Permission catalog: ordered groups of (code, label). Codes are dot-namespaced `<area>.<verb>`.
# ---------------------------------------------------------------------------
PERMISSION_CATALOG = [
    ('Requisitions', [
        ('requisition.view', 'View requisitions'),
        ('requisition.create', 'Create / amend requisitions'),
        ('requisition.approve', 'Approve requisitions'),
    ]),
    ('Purchase Orders', [
        ('po.view', 'View purchase orders'),
        ('po.manage', 'Create / edit purchase orders'),
        ('po.issue', 'Issue purchase orders to vendors'),
    ]),
    ('Vendors', [
        ('vendor.view', 'View vendors'),
        ('vendor.manage', 'Onboard / edit vendors'),
        ('vendor.blacklist', 'Suspend / blacklist vendors'),
    ]),
    ('Sourcing & RFx', [
        ('sourcing.view', 'View sourcing events & RFx'),
        ('sourcing.manage', 'Run sourcing events & RFx'),
        ('sourcing.award', 'Award sourcing events'),
    ]),
    ('Contracts', [
        ('contract.view', 'View contracts'),
        ('contract.manage', 'Author / amend contracts'),
    ]),
    ('Catalog', [
        ('catalog.view', 'View catalog'),
        ('catalog.manage', 'Manage catalog items & pricing'),
    ]),
    ('Invoices & Payments', [
        ('invoice.view', 'View invoices'),
        ('invoice.manage', 'Process invoices'),
        ('invoice.pay', 'Approve / pay vouchers'),
    ]),
    ('Inventory & Receiving', [
        ('inventory.view', 'View stock & receipts'),
        ('inventory.manage', 'Post goods movements & receipts'),
    ]),
    ('Analytics & Budget', [
        ('analytics.view', 'View spend analytics & reports'),
        ('budget.manage', 'Manage budgets'),
    ]),
    ('Documents', [
        ('document.view', 'View documents & knowledge base'),
        ('document.manage', 'Manage documents & templates'),
    ]),
    ('System Administration', [
        ('sysadmin.view', 'View system administration'),
        ('sysadmin.manage', 'Manage system administration & security'),
    ]),
]

# Flat helpers
ALL_PERMISSION_CODES = [code for _group, perms in PERMISSION_CATALOG for code, _label in perms]
PERMISSION_LABELS = {code: label for _group, perms in PERMISSION_CATALOG for code, label in perms}


def is_valid_permission(code):
    return code in PERMISSION_LABELS


# ---------------------------------------------------------------------------
# Default grant matrix — mirrors the *current* hardcoded behaviour of the app so seeding the matrix
# changes nothing observable. ``__all__`` is a sentinel meaning "every catalog code".
# ---------------------------------------------------------------------------
_ALL = '__all__'

DEFAULT_ROLE_GRANTS = {
    'super_admin': _ALL,
    'tenant_admin': _ALL,
    'procurement_manager': [
        'requisition.view', 'requisition.create', 'requisition.approve',
        'po.view', 'po.manage', 'po.issue',
        'vendor.view', 'vendor.manage', 'vendor.blacklist',
        'sourcing.view', 'sourcing.manage', 'sourcing.award',
        'contract.view', 'contract.manage',
        'catalog.view', 'catalog.manage',
        'invoice.view', 'invoice.manage', 'invoice.pay',
        'inventory.view', 'inventory.manage',
        'analytics.view', 'budget.manage',
        'document.view', 'document.manage',
        'sysadmin.view',
    ],
    'buyer': [
        'requisition.view', 'requisition.create',
        'po.view', 'po.manage', 'po.issue',
        'vendor.view', 'vendor.manage',
        'sourcing.view', 'sourcing.manage',
        'contract.view', 'catalog.view', 'catalog.manage',
        'invoice.view', 'invoice.manage',
        'inventory.view', 'inventory.manage',
        'analytics.view', 'document.view', 'document.manage',
    ],
    'approver': [
        'requisition.view', 'requisition.approve',
        'po.view', 'vendor.view', 'sourcing.view', 'contract.view',
        'catalog.view', 'invoice.view', 'inventory.view',
        'analytics.view', 'document.view',
    ],
    'requester': [
        'requisition.view', 'requisition.create',
        'po.view', 'catalog.view', 'document.view',
    ],
    'viewer': [
        'requisition.view', 'po.view', 'vendor.view', 'sourcing.view',
        'contract.view', 'catalog.view', 'invoice.view', 'inventory.view',
        'analytics.view', 'document.view',
    ],
    'vendor_portal': [],
}


def default_grants_for(role_code):
    """Return the list of permission codes granted by default to ``role_code``."""
    grant = DEFAULT_ROLE_GRANTS.get(role_code, [])
    if grant == _ALL:
        return list(ALL_PERMISSION_CODES)
    return list(grant)
