import os
from datetime import timedelta

import structlog
from config.django.base import *  # NOQA
from decouple import config

allowed_hosts = str(config('ALLOWED_HOSTS', default=''))
ALLOWED_HOSTS = (
    allowed_hosts.split()
    if allowed_hosts
    else [
        '127.0.0.1',
        'localhost',
    ]
)

SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=True, cast=bool)

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = config(
    'SECURE_CONTENT_TYPE_NOSNIFF', default=True, cast=bool
)

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(
        minutes=config('ACCESS_TOKEN_LIFETIME', default=60, cast=int),
    ),
    'REFRESH_TOKEN_LIFETIME': timedelta(
        days=config('REFRESH_TOKEN_LIFETIME', default=7, cast=int),
    ),
    'AUTH_COOKIE': 'access_token',
    'AUTH_COOKIE_REFRESH': 'refresh_token',
    'AUTH_COOKIE_DOMAIN': None,
    'AUTH_COOKIE_SECURE': True,
    'AUTH_COOKIE_HTTP_ONLY': True,
    'AUTH_COOKIE_PATH': '/',
    'AUTH_COOKIE_SAMESITE': 'Lax',
    'AUTH_COOKIE_MAX_AGE': config('ACCESS_TOKEN_LIFETIME', default=60, cast=int) * 60,
    'AUTH_COOKIE_REFRESH_MAX_AGE': config('REFRESH_TOKEN_LIFETIME', default=7, cast=int)
    * 24
    * 60
    * 60,
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': structlog.stdlib.ProcessorFormatter,
            'processor': structlog.processors.JSONRenderer(),
        },
    },
    'handlers': {
        'json_file': {
            'class': 'logging.handlers.WatchedFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'hlvm.log'),  # noqa: F405
            'formatter': 'json',
        },
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'loggers': {
        'django_structlog': {
            'handlers': ['json_file', 'console'],
            'level': 'INFO',
        },
        'myproject': {  # Замените на имя вашего Django-проекта
            'handlers': ['json_file', 'console'],
            'level': 'INFO',
        },
    },
}

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt='iso'),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
