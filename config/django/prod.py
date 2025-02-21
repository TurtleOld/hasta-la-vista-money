import os

from config.django.base import *  # NOQA

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split() or [
    '127.0.0.1',
    'localhost',
]

SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', default=True)

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', default=True)
SECURE_CONTENT_TYPE_NOSNIFF = os.environ.get(
    'SECURE_CONTENT_TYPE_NOSNIFF',
    default=True,
)
