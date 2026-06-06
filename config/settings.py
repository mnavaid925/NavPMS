"""Django settings for NavPMS — Procurement Management System."""
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Third party
    'crispy_forms',
    'crispy_bootstrap5',

    # Local
    'apps.core',
    'apps.accounts',
    'apps.tenants',
    'apps.portal',
    'apps.requisitions',
    'apps.approvals',
    'apps.vendors',
    'apps.sourcing',
    'apps.rfx',
    'apps.auctions',
    'apps.contracts',
    'apps.catalog',
    'apps.purchase_orders',
    'apps.fulfillment',
    'apps.goods_receipt',
    'apps.invoicing',
    'apps.spend_analytics',
    'apps.budget',
    'apps.supplier_performance',
    'apps.compliance',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.core.middleware.TenantMiddleware',
    'apps.vendors.middleware.VendorPortalSandboxMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.core.context_processors.tenant_context',
                'apps.core.context_processors.ui_preferences',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': config('DB_ENGINE', default='django.db.backends.mysql'),
        'NAME': config('DB_NAME', default='navpms'),
        'USER': config('DB_USER', default='root'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='127.0.0.1'),
        'PORT': config('DB_PORT', default='3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = config('LANGUAGE_CODE', default='en-us')
TIME_ZONE = config('TIME_ZONE', default='UTC')
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.User'

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

LOGIN_URL = config('LOGIN_URL', default='/accounts/login/')
LOGIN_REDIRECT_URL = config('LOGIN_REDIRECT_URL', default='/')
LOGOUT_REDIRECT_URL = config('LOGOUT_REDIRECT_URL', default='/accounts/login/')

APP_NAME = config('APP_NAME', default='NavPMS')

EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='no-reply@navpms.local')

PAYMENT_GATEWAY = config('PAYMENT_GATEWAY', default='mock')

# Module 10 — Catalog punch-out. Selects the default punch-out connector
# (cxml / oci / loopback) and an optional comma-separated SSRF allowlist of
# extra hosts the setup URL may target (used for testing against a known host).
PUNCHOUT_CONNECTOR = config('PUNCHOUT_CONNECTOR', default='cxml')
PUNCHOUT_SSRF_ALLOWLIST = config('PUNCHOUT_SSRF_ALLOWLIST', default='')

# Module 12 — Order Fulfillment freight tracking. Selects the default carrier
# connector (mock by default; real carriers wire in via apps/fulfillment/carriers.py)
# and an optional comma-separated SSRF allowlist of extra hosts a real carrier's
# tracking endpoint may target.
FREIGHT_CARRIER = config('FREIGHT_CARRIER', default='mock')
FREIGHT_TRACKING_ALLOWLIST = config('FREIGHT_TRACKING_ALLOWLIST', default='')

# Module 14 — Invoice & Voucher Management. Selects the default invoice OCR engine
# (mock by default; real engines wire in via apps/invoicing/ocr.py) and the default
# three-way-match tolerances (percent) applied when matching an invoice line's quantity
# and unit price against the PO + Goods Receipt.
OCR_ENGINE = config('OCR_ENGINE', default='mock')
INVOICE_QTY_TOLERANCE_PCT = config('INVOICE_QTY_TOLERANCE_PCT', default='2', cast=float)
INVOICE_PRICE_TOLERANCE_PCT = config('INVOICE_PRICE_TOLERANCE_PCT', default='2', cast=float)
# OCR captures below this confidence (percent) are flagged for manual review in the UI.
OCR_MIN_CONFIDENCE = config('OCR_MIN_CONFIDENCE', default='70', cast=float)
# Days a dispute may stay open before the escalation alert fires (scan_invoice_alerts).
INVOICE_DISPUTE_SLA_DAYS = config('INVOICE_DISPUTE_SLA_DAYS', default='5', cast=int)
# Opt-in: also email the invoice owner on overdue / closing-discount / dispute-SLA alerts
# (in addition to the in-app portal notification). Off by default; needs a real EMAIL_BACKEND.
INVOICE_EMAIL_ALERTS = config('INVOICE_EMAIL_ALERTS', default=False, cast=bool)

# Module 16 — Budget & Cost Management. Controls the real-time budget-availability check fired
# when a requisition is submitted: 'warn' (default) flags an over-budget requisition + alerts the
# budget owner but lets it through; 'block' raises a validation error and stops the submission.
# The variance tolerance (percent) and warn-utilization threshold drive the variance flags and the
# one-time over-budget cron alert (scan_budget_alerts).
BUDGET_ENFORCEMENT = config('BUDGET_ENFORCEMENT', default='warn')
BUDGET_VARIANCE_TOLERANCE_PCT = config('BUDGET_VARIANCE_TOLERANCE_PCT', default='10', cast=float)
BUDGET_WARN_UTILIZATION_PCT = config('BUDGET_WARN_UTILIZATION_PCT', default='90', cast=float)

# Module 18 — Risk & Compliance Management. Selects the pluggable restricted-party screening
# provider and supplier credit-score provider (both mock by default; real providers wire in via
# apps/compliance/screening.py and apps/compliance/credit.py), with optional comma-separated SSRF
# allowlists of extra hosts a real provider endpoint may target. SCREENING_MATCH_THRESHOLD is the
# fuzzy-match percent at/above which a screening records a hit; CREDIT_SCORE_DROP_ALERT is the
# score-drop (points) that raises a financial-risk alert. The FRAUD_* values tune the fraud
# detectors (scan_fraud); POLICY_ACK_REMINDER_DAYS paces the cron acknowledgment reminders.
SCREENING_PROVIDER = config('SCREENING_PROVIDER', default='mock')
SCREENING_ALLOWLIST = config('SCREENING_ALLOWLIST', default='')
SCREENING_MATCH_THRESHOLD = config('SCREENING_MATCH_THRESHOLD', default='85', cast=float)
CREDIT_PROVIDER = config('CREDIT_PROVIDER', default='mock')
CREDIT_ALLOWLIST = config('CREDIT_ALLOWLIST', default='')
CREDIT_SCORE_DROP_ALERT = config('CREDIT_SCORE_DROP_ALERT', default='10', cast=float)
FRAUD_SPLIT_PO_WINDOW_DAYS = config('FRAUD_SPLIT_PO_WINDOW_DAYS', default='14', cast=int)
FRAUD_ROUND_AMOUNT_FLOOR = config('FRAUD_ROUND_AMOUNT_FLOOR', default='5000', cast=float)
POLICY_ACK_REMINDER_DAYS = config('POLICY_ACK_REMINDER_DAYS', default='14', cast=int)

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7

# Security hardening (SQA defect D-09). Applied only outside DEBUG so local
# XAMPP development over plain HTTP is unaffected.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
if not DEBUG:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
