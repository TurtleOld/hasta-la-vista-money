from decouple import config

from hasta_la_vista_money import constants

SESSION_COOKIE_AGE = config(
    'SESSION_COOKIE_AGE',
    default=constants.SESSION_COOKIE_AGE,
    cast=int,
)
SESSION_COOKIE_HTTPONLY = config(
    'SESSION_COOKIE_HTTPONLY', default=True, cast=bool
)
SESSION_COOKIE_NAME = config('SESSION_COOKIE_NAME', default='sessionid')
SESSION_COOKIE_SAMESITE = config('SESSION_COOKIE_SAMESITE', default='Lax')
SESSION_COOKIE_SECURE = config(
    'SESSION_COOKIE_SECURE', default='true'
).lower() in {'true', '1', 't'}
