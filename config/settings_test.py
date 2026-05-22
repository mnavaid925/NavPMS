"""Fast settings for the automated test suite.

In-memory SQLite + MD5 hashing for speed; HTTPS hardening from settings.py
(SQA defect D-09) is disabled so the Django test client (plain HTTP) is not
bounced by SECURE_SSL_REDIRECT.
"""
from config.settings import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Undo the production HTTPS hardening so the HTTP test client works.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
