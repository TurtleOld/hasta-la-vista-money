from typing import TYPE_CHECKING, Any

from django.conf import settings

if TYPE_CHECKING:
    from drf_spectacular.extensions import (
        OpenApiAuthenticationExtension as _OpenApiAuthExt,
    )
else:
    from drf_spectacular.extensions import (
        OpenApiAuthenticationExtension as _OpenApiAuthExt,
    )


class CookieJWTAuthenticationScheme(_OpenApiAuthExt):  # type: ignore[no-untyped-call]
    """Authentication scheme for drf-spectacular.

    Note: type: ignore[no-untyped-call] is needed due to drf-spectacular's
    __init_subclass__ implementation which is not fully typed.
    """

    target_class = (
        'hasta_la_vista_money.authentication.authentication.'
        'CookieJWTAuthentication'
    )
    name = 'CookieJWTAuth'

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        cookie_name = str(
            settings.SIMPLE_JWT.get('AUTH_COOKIE', 'access_token')
        )
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': cookie_name,
            'description': 'JWT токен в HttpOnly cookie для аутентификации',
        }
