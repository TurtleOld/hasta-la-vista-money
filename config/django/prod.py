from config.env import env
from config.django.base import *  # NOQA

ALLOWED_HOSTS = env.bool('ALLOWED_HOSTS', '').split() or ['127.0.0.1',
                                                          'localhost']

SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
    "SECURE_CONTENT_TYPE_NOSNIFF",
    default=True,
)
