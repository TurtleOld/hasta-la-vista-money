import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict

import dj_database_url
import django_stubs_ext
import sentry_sdk
import structlog
from config.django.sessions import *  # NOQA
from config.settings.debug_toolbar.setup import DebugToolbarSetup
from csp.constants import NONCE, SELF
from dotenv import load_dotenv
from sentry_sdk.integrations.django import DjangoIntegration

django_stubs_ext.monkeypatch()
load_dotenv()

# Security settings
SECRET_KEY = os.getenv('SECRET_KEY', None)
DEBUG = os.getenv('DEBUG', 'false').lower() in {'true', '1', 't'}
BASE_URL = os.getenv('BASE_URL') or 'http://127.0.0.1:8000/'
BASE_DIR = Path(__file__).resolve().parent.parent.parent

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(',')
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', '').split() or []
INTERNAL_IPS = [
    (
        os.environ.get(
            'LOCAL_IPS',
        )
        if os.environ.get(
            'LOCAL_IPS',
        )
        else '127.0.0.1'
    ),
]

# Application definition
LOCAL_APPS = [
    'hasta_la_vista_money',
    'hasta_la_vista_money.api',
    'hasta_la_vista_money.authentication',
    'hasta_la_vista_money.finance_account',
    'hasta_la_vista_money.budget',
    'hasta_la_vista_money.expense',
    'hasta_la_vista_money.income',
    'hasta_la_vista_money.loan',
    'hasta_la_vista_money.receipts',
    'hasta_la_vista_money.reports',
    'hasta_la_vista_money.users',
    'hasta_la_vista_money.templatetags.thousand_comma',
    'hasta_la_vista_money.templatetags.generate_hash',
]

THIRD_PARTY_APPS = [
    'axes',
    'csp',
    'crispy_forms',
    'crispy_bootstrap5',
    'django_filters',
    'locale',
    'rest_framework',
    'rest_framework.authtoken',
    'rosetta',
    'django_structlog',
]

if DEBUG:
    THIRD_PARTY_APPS.append('django_extensions')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.humanize',
    'django.contrib.messages',
    'django.contrib.sessions',
    'django.contrib.staticfiles',
    *LOCAL_APPS,
    *THIRD_PARTY_APPS,
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'csp.middleware.CSPMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'hasta_la_vista_money.users.middleware.CheckAdminMiddleware',
    'axes.middleware.AxesMiddleware',
    'django_structlog.middlewares.RequestMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'hasta_la_vista_money', 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            'libraries': {
                'comma': 'hasta_la_vista_money.templatetags.thousand_comma',
                'word_hash': 'hasta_la_vista_money.templatetags.generate_hash',
                'dict_get': 'hasta_la_vista_money.templatetags.dict_get',
                'index': 'hasta_la_vista_money.templatetags.index',
            },
        },
    },
]

CONN_MAX_AGE = 500

# Database
if os.getenv('DATABASE_URL') or os.getenv('POSTGRES_DB'):
    DATABASES: Dict[str, Any] = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB', 'postgres'),
            'USER': os.getenv('POSTGRES_USER', 'postgres'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'postgres'),
            'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
            'CONN_MAX_AGE': CONN_MAX_AGE,
        },
    }
    if os.environ.get('GITHUB_WORKFLOW'):
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': 'github_actions',
                'USER': 'postgres',
                'PASSWORD': 'postgres',
                'HOST': '127.0.0.1',
                'PORT': '5432',
            },
        }
    if os.getenv('DATABASE_URL'):
        DATABASES['default'] = dict(dj_database_url.config(conn_max_age=CONN_MAX_AGE))
else:
    DATABASES: Dict[str, Any] = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        },
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTHENTICATION_BACKENDS = (
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
)

# Internationalization
LANGUAGE_CODE = os.getenv('LANGUAGE_CODE', 'ru-RU')
TIME_ZONE = os.getenv('TIME_ZONE', 'Europe/Moscow')
USE_I18N = True
USE_TZ = False
LANGUAGES = (
    ('en', 'English'),
    ('ru-RU', 'Russian'),
)
LOCALE_PATHS = (os.path.join(BASE_DIR, 'locale'),)

APPEND_SLASH = True

# Static files
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = 'static/'
STATICFILES_DIRS = (os.path.join(BASE_DIR, 'static'),)

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Content Security Policy (CSP)
CSP_CDN_URLS = [
    'https://cdn.jsdelivr.net',
    'https://unpkg.com',
    'https://htmx.org',
    'https://cdn.datatables.net',
    'https://cdnjs.cloudflare.com',
]
additional_script_src = list(
    filter(None, os.environ.get('URL_CSP_SCRIPT_SRC', '').split(',')),
)
CONTENT_SECURITY_POLICY = {
    'EXCLUDE_URL_PREFIXES': ['/admin'],
    'DIRECTIVES': {
        'default-src': [
            SELF,
            NONCE,
            BASE_URL,
            *CSP_CDN_URLS,
        ]
        + additional_script_src,
        'script-src': [
            SELF,
            NONCE,
            BASE_URL,
            *CSP_CDN_URLS,
        ]
        + additional_script_src,
        'img-src': [
            SELF,
            NONCE,
            'data:',
            BASE_URL,
            *CSP_CDN_URLS,
        ],
        'style-src': [
            SELF,
            NONCE,
            BASE_URL,
            *CSP_CDN_URLS,
        ]
        + additional_script_src,
        'font-src': [
            SELF,
            NONCE,
            BASE_URL,
            *CSP_CDN_URLS,
        ]
        + additional_script_src,
        'frame-ancestors': [
            SELF,
            *CSP_CDN_URLS,
        ]
        + additional_script_src,
        'report_uri': [os.getenv('SENTRY_ENDPOINT')],
    },
}

# Authentication and user settings
AUTH_USER_MODEL = 'users.User'
LOGIN_REDIRECT_URL = '/'
LOGIN_URL = '/login/'
LOGOUT_REDIRECT_URL = '/login'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_FILTER_BACKENDS': ('django_filters.rest_framework.DjangoFilterBackend',),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
}

# Sentry
RATE = 0.01
SENTRY_DSN = os.getenv('SENTRY_DSN')
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        auto_session_tracking=False,
        traces_sample_rate=RATE,
        environment=os.getenv('SENTRY_ENVIRONMENT'),
    )

# Rosetta
ROSETTA_ENABLE_TRANSLATION_SUGGESTIONS = True
ROSETTA_MESSAGES_SOURCE_LANGUAGE_CODE = 'ru'
ROSETTA_MESSAGES_SOURCE_LANGUAGE_NAME = 'Russian'
ROSETTA_LANGUAGE_GROUPS = True
ROSETTA_STORAGE_CLASS = 'rosetta.storage.CacheRosettaStorage'
ROSETTA_WSGI_AUTO_RELOAD = True
ROSETTA_UWSGI_AUTO_RELOAD = True

# Crispy Forms
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# Debug Toolbar
INSTALLED_APPS, MIDDLEWARE = DebugToolbarSetup.do_settings(
    INSTALLED_APPS,
    MIDDLEWARE,
)

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(
        minutes=int(os.environ.get('ACCESS_TOKEN_LIFETIME', '60')),
    ),
    'REFRESH_TOKEN_LIFETIME': timedelta(
        days=int(os.environ.get('REFRESH_TOKEN_LIFETIME', '7')),
    ),
}

if not os.path.exists(os.path.join(BASE_DIR, 'logs')):
    os.mkdir(os.path.join(BASE_DIR, 'logs'))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {
            '()': structlog.stdlib.ProcessorFormatter,
            'processor': structlog.dev.ConsoleRenderer(),
        },
        'key_value': {
            '()': structlog.stdlib.ProcessorFormatter,
            'processor': structlog.processors.KeyValueRenderer(
                key_order=['timestamp', 'level', 'event', 'logger'],
            ),
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'console',
        },
        'flat_line_file': {
            'class': 'logging.handlers.WatchedFileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'hlvm.log'),
            'formatter': 'key_value',
        },
    },
    'loggers': {
        'django_structlog': {
            'handlers': ['console', 'flat_line_file'],
            'level': 'DEBUG',
        },
        'myproject': {  # Замените на имя вашего Django-проекта
            'handlers': ['console', 'flat_line_file'],
            'level': 'DEBUG',
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
        structlog.dev.set_exc_info,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
