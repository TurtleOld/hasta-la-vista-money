import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict
import dj_database_url
import django_stubs_ext
import sentry_sdk
import structlog
from config.django.sessions import *  # NOQA
from config.django.validator_env import EnvironmentValidator
from config.settings.debug_toolbar.setup import DebugToolbarSetup
from csp.constants import NONCE, SELF
from decouple import config
from sentry_sdk.integrations.django import DjangoIntegration

django_stubs_ext.monkeypatch()

# Security settings
if (
    'collectstatic' not in sys.argv
    and 'migrate' not in sys.argv
    and 'test' not in sys.argv
):
    if not EnvironmentValidator().validate():
        raise ValueError('Environment variables are not valid')
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
BASE_URL = config('BASE_URL', default='http://127.0.0.1:8000/')
BASE_DIR = Path(__file__).resolve().parent.parent.parent

allowed_hosts = str(config('ALLOWED_HOSTS', default=''))
ALLOWED_HOSTS = allowed_hosts.split(',') if allowed_hosts else []
csrf_trusted_origins = str(config('CSRF_TRUSTED_ORIGINS', default=''))
CSRF_TRUSTED_ORIGINS = csrf_trusted_origins.split() if csrf_trusted_origins else []
INTERNAL_IPS = [config('LOCAL_IPS', default='127.0.0.1')]

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
    'corsheaders',
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


if not DEBUG:
    THIRD_PARTY_APPS.append('django_redis')

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
    'corsheaders.middleware.CorsMiddleware',
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
    'hasta_la_vista_money.compressor_middleware.CompressorNonceMiddleware',
    'django_structlog.middlewares.RequestMiddleware',
]


if 'test' not in sys.argv:
    MIDDLEWARE.append('axes.middleware.AxesMiddleware')
else:
    MIDDLEWARE = [
        mw
        for mw in MIDDLEWARE
        if mw != 'hasta_la_vista_money.users.middleware.CheckAdminMiddleware'
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

CONN_MAX_AGE = config('CONN_MAX_AGE', default=60, cast=int)

# Cache configuration
if DEBUG:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
            'TIMEOUT': 300,
            'OPTIONS': {
                'MAX_ENTRIES': 1000,
            },
        },
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': config('REDIS_LOCATION', cast=str),
            'OPTIONAL': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
        },
    }

# Database
if 'test' in sys.argv and not config('USE_DB_FOR_TESTS', default=False, cast=bool):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        },
    }
else:
    if config('GITHUB_WORKFLOW', default=''):
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
    elif config('DATABASE_URL', default='') or config('POSTGRES_DB', default=''):
        DATABASES: Dict[str, Any] = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': config('POSTGRES_DB', default='postgres'),
                'USER': config('POSTGRES_USER', default='postgres'),
                'PASSWORD': config('POSTGRES_PASSWORD', default='postgres'),
                'HOST': config('POSTGRES_HOST', default='localhost'),
                'PORT': config('POSTGRES_PORT', default='5432'),
                'CONN_MAX_AGE': CONN_MAX_AGE,
            },
        }
        database_url = config('DATABASE_URL', default='')
        if database_url:
            DATABASES['default'] = dict(
                dj_database_url.parse(str(database_url), conn_max_age=CONN_MAX_AGE),
            )
    else:
        DATABASES = {
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

# Axes settings for performance optimization
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_LOCKOUT_TEMPLATE = None
AXES_VERBOSE = False
AXES_ENABLE_ADMIN = False
if 'test' in sys.argv:
    AXES_ENABLED = False

# Internationalization
LANGUAGE_CODE = config('LANGUAGE_CODE', default='ru-RU')
TIME_ZONE = config('TIME_ZONE', default='Europe/Moscow')
USE_I18N = True
USE_TZ = True
LANGUAGES = (
    ('en', 'English'),
    ('ru-RU', 'Russian'),
)
LOCALE_PATHS = (os.path.join(BASE_DIR, 'locale'),)

APPEND_SLASH = True

# Static files
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = '/static/'
STATICFILES_DIRS = (os.path.join(BASE_DIR, 'static'),)

# WhiteNoise configuration for static files
STORAGE = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# WhiteNoise settings
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_MAX_AGE = 31536000  # 1 year
WHITENOISE_INDEX_FILE = True
WHITENOISE_ROOT = os.path.join(BASE_DIR, 'staticfiles')
WHITENOISE_BROTLI = True

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
    filter(None, str(config('URL_CSP_SCRIPT_SRC', default='')).split(',')),
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
        'report_uri': [config('SENTRY_ENDPOINT', default='')],
    },
}

# Authentication and user settings
AUTH_USER_MODEL = 'users.User'
LOGIN_REDIRECT_URL = '/'
LOGIN_URL = '/login/'
LOGOUT_REDIRECT_URL = '/login'

# CORS settings for mobile app
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in str(config('CORS_ALLOWED_ORIGINS', default='')).split(',')
    if origin.strip()
] or [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:8080',
    'http://127.0.0.1:8080',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_FILTER_BACKENDS': ('django_filters.rest_framework.DjangoFilterBackend',),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'hasta_la_vista_money.authentication.authentication.CookieJWTAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'login': '5/min',
    },
}

# Sentry
RATE = 0.01
SENTRY_DSN = config('SENTRY_DSN', default='')
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=str(SENTRY_DSN),
        integrations=[DjangoIntegration()],
        auto_session_tracking=False,
        traces_sample_rate=RATE,
        environment=str(config('SENTRY_ENVIRONMENT', default='')),
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
        minutes=config('ACCESS_TOKEN_LIFETIME', default=60, cast=int),
    ),
    'REFRESH_TOKEN_LIFETIME': timedelta(
        days=config('REFRESH_TOKEN_LIFETIME', default=7, cast=int),
    ),
    'AUTH_COOKIE': 'access_token',
    'AUTH_COOKIE_REFRESH': 'refresh_token',
    'AUTH_COOKIE_DOMAIN': None,
    'AUTH_COOKIE_SECURE': config('SESSION_COOKIE_SECURE', default=False, cast=bool),
    'AUTH_COOKIE_HTTP_ONLY': True,
    'AUTH_COOKIE_PATH': '/',
    'AUTH_COOKIE_SAMESITE': 'Lax',
    'AUTH_COOKIE_MAX_AGE': config('ACCESS_TOKEN_LIFETIME', default=60, cast=int) * 60,
    'AUTH_COOKIE_REFRESH_MAX_AGE': config('REFRESH_TOKEN_LIFETIME', default=7, cast=int)
    * 24
    * 60
    * 60,
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
            'level': 'WARNING',
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


# Compressor settings
COMPRESS_ENABLED = config('COMPRESS_ENABLED', default=False, cast=bool)
INSTALLED_APPS.append('compressor')
COMPRESS_ROOT = os.path.join(BASE_DIR, 'staticfiles')
COMPRESS_URL = '/static/'
COMPRESS_STORAGE = 'compressor.storage.GzipCompressorFileStorage'
COMPRESS_STORAGE_ALIAS = 'compressor'
COMPRESS_OFFLINE = False
COMPRESS_BROTLI = True
COMPRESS_CSS_FILTERS = [
    'compressor.filters.cssmin.CSSMinFilter',
]
COMPRESS_JS_FILTERS = [
    'compressor.filters.jsmin.JSMinFilter',
]

COMPRESS_CSS_HASHING_METHOD = 'mtime'
COMPRESS_JS_HASHING_METHOD = 'mtime'
COMPRESS_OUTPUT_DIR = ''
COMPRESS_OFFLINE_CONTEXT = {
    'STATIC_URL': STATIC_URL,
}
STATICFILES_FINDERS = [
    'compressor.finders.CompressorFinder',
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
]
