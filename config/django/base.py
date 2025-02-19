import dj_database_url
import django_stubs_ext
import sentry_sdk
from config.django.sessions import *  # NOQA
from dotenv import load_dotenv
from sentry_sdk.integrations.django import DjangoIntegration
from config.settings.debug_toolbar.setup import DebugToolbarSetup
from config.env import BASE_DIR, env, APPS_DIR
import os

django_stubs_ext.monkeypatch()
load_dotenv()
env.read_env(os.path.join(BASE_DIR, ".env"))

# Security settings
SECRET_KEY = os.getenv('SECRET_KEY', None)
DEBUG = os.getenv('DEBUG', 'false').lower() in {'true', '1', 't'}
BASE_URL = os.getenv('BASE_URL') or 'http://127.0.0.1:8000/'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(',')
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', '').split() or []
INTERNAL_IPS = [
    os.environ.get(
        'LOCAL_IPS',
    )
    if os.environ.get(
        'LOCAL_IPS',
    )
    else '127.0.0.1',
]

# Application definition
LOCAL_APPS = [
    'hasta_la_vista_money',
    'hasta_la_vista_money.api',
    'hasta_la_vista_money.authentication',
    'hasta_la_vista_money.finance_account',
    'hasta_la_vista_money.budget',
    'hasta_la_vista_money.commonlogic',
    'hasta_la_vista_money.expense',
    'hasta_la_vista_money.income',
    'hasta_la_vista_money.loan',
    'hasta_la_vista_money.receipts',
    'hasta_la_vista_money.reports',
    'hasta_la_vista_money.users',
    'hasta_la_vista_money.templatags.thousand_comma',
    'hasta_la_vista_money.templatags.generate_hash',
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
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(APPS_DIR, "templates")],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            'libraries': {
                'comma': 'hasta_la_vista_money.templatags.thousand_comma',
                'word_hash': 'hasta_la_vista_money.templatags.generate_hash',
            },
        },
    },
]

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB', 'postgres'),
        'USER': os.getenv('POSTGRES_USER', 'postgres'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'postgres'),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'),
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

CONN_MAX_AGE = 500
if os.getenv('DATABASE_URL'):
    DATABASES['default'] = dj_database_url.config(conn_max_age=CONN_MAX_AGE)

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTHENTICATION_BACKENDS = (
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
)

# Internationalization
LANGUAGE_CODE = 'ru-RU'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_L10N = True
USE_TZ = False
LANGUAGES = (
    ('en', 'English'),
    ('ru-RU', 'Russian'),
)
LOCALE_PATHS = (os.path.join(BASE_DIR, 'locale'),)

# Static files
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = 'static/'
STATICFILES_DIRS = (os.path.join(BASE_DIR, 'static'),)

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Content Security Policy (CSP)
CSP_INCLUDE_NONCE_IN = ['script-src', 'style-src', 'img-src', 'font-src']
CSP_REPORT_URI = [os.getenv('SENTRY_ENDPOINT')]
CSP_DEFAULT_SRC = ("'self'", BASE_URL, 'https://code.highcharts.com')
CSP_SCRIPT_SRC = (
    "'self'", '127.0.0.1', BASE_URL, 'https://code.highcharts.com')
CSP_STYLE_SRC = ("'self'", BASE_URL, 'https://code.highcharts.com')
CSP_IMG_SRC = ("'self'", 'data:', BASE_URL)
CSP_FONT_SRC = ("'self'", BASE_URL)
CSP_FRAME_SRC = ("'none'",)
CSP_BASE_URI = ("'none'",)
CSP_OBJECT_SRC = ("'none'",)

# Authentication and user settings
AUTH_USER_MODEL = 'users.User'
LOGIN_REDIRECT_URL = '/'
LOGIN_URL = '/login/'
LOGOUT_REDIRECT_URL = '/login'

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_FILTER_BACKENDS': 'django_filters.rest_framework.DjangoFilterBackend',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
}

# Sentry
RATE = 0.01
sentry_sdk.init(
    dsn=os.getenv('SENTRY_DSN'),
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

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
}
