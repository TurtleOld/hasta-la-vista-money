import os
from datetime import timedelta

import structlog
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

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.environ.get('ACCESS_TOKEN_LIFETIME', '60'))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.environ.get('REFRESH_TOKEN_LIFETIME', '7'))),
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
