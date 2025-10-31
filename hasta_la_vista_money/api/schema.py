from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class CookieJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = (
        'hasta_la_vista_money.authentication.authentication.'
        'CookieJWTAuthentication'
    )
    name = 'CookieJWTAuth'

    def get_security_definition(self, auto_schema):
        cookie_name = str(
            settings.SIMPLE_JWT.get('AUTH_COOKIE', 'access_token')
        )
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': cookie_name,
            'description': 'JWT токен в HttpOnly cookie для аутентификации',
        }
