from typing import Literal, ParamSpec, TypeVar, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext_lazy as _
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import Token

from hasta_la_vista_money.users.models import User

T = TypeVar('T', bound=HttpResponse)
P = ParamSpec('P')
SameSite = Literal['Strict', 'Lax', 'None'] | None


class CookieJWTAuthentication(JWTAuthentication):
    """Custom JWT authentication that uses HttpOnly cookies
    instead of Authorization header"""

    def authenticate(self, request: Request) -> tuple[User, Token] | None:  # type: ignore[override]
        cookie_token = request.COOKIES.get(
            str(settings.SIMPLE_JWT['AUTH_COOKIE']),
        )

        if cookie_token is not None:
            raw_token = cookie_token.encode('utf-8')
        else:
            header = self.get_header(request)
            if header is None:
                return None  # type: ignore[unreachable]
            raw_token_raw = self.get_raw_token(header)
            if raw_token_raw is None:
                return None
            raw_token = raw_token_raw

        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)

            if not isinstance(user, User):
                self._raise_invalid_user_type(user)
                return None
        except TypeError:
            raise
        except (
            InvalidToken,
            ValueError,
            KeyError,
            AttributeError,
            ImportError,
            RuntimeError,
            OSError,
        ):
            return None
        else:
            return user, validated_token

    def _raise_invalid_user_type(self, user: object) -> None:
        raise TypeError(
            _('Ожидался экземпляр User, получен {type_name}').format(
                type_name=type(user),
            ),
        )

    def authenticate_header(self, request: Request) -> str:
        return 'Bearer realm="api"'


def set_auth_cookies[T: HttpResponse](
    response: T,
    access_token: str,
    refresh_token: str | None = None,
) -> T:
    """Set JWT tokens as HttpOnly cookies in the response"""
    jwt_settings = settings.SIMPLE_JWT
    samesite_value: SameSite = None
    samesite_setting = jwt_settings.get('AUTH_COOKIE_SAMESITE')
    if samesite_setting:
        samesite_str = str(samesite_setting)
        if samesite_str in ('Strict', 'Lax', 'None'):
            samesite_value = cast('SameSite', samesite_str)
        else:
            samesite_value = None

    response.set_cookie(
        str(jwt_settings['AUTH_COOKIE']),
        access_token,
        max_age=(
            cast('int', jwt_settings['AUTH_COOKIE_MAX_AGE'])
            if jwt_settings['AUTH_COOKIE_MAX_AGE'] is not None
            else None
        ),
        domain=str(jwt_settings['AUTH_COOKIE_DOMAIN'])
        if jwt_settings['AUTH_COOKIE_DOMAIN']
        else None,
        secure=bool(jwt_settings['AUTH_COOKIE_SECURE']),
        httponly=bool(jwt_settings['AUTH_COOKIE_HTTP_ONLY']),
        samesite=samesite_value,
        path=str(jwt_settings['AUTH_COOKIE_PATH']),
    )
    if refresh_token:
        response.set_cookie(
            str(jwt_settings['AUTH_COOKIE_REFRESH']),
            refresh_token,
            max_age=(
                cast('int', jwt_settings['AUTH_COOKIE_REFRESH_MAX_AGE'])
                if jwt_settings['AUTH_COOKIE_REFRESH_MAX_AGE'] is not None
                else None
            ),
            domain=str(jwt_settings['AUTH_COOKIE_DOMAIN'])
            if jwt_settings['AUTH_COOKIE_DOMAIN']
            else None,
            secure=bool(jwt_settings['AUTH_COOKIE_SECURE']),
            httponly=bool(jwt_settings['AUTH_COOKIE_HTTP_ONLY']),
            samesite=samesite_value,
            path=str(jwt_settings['AUTH_COOKIE_PATH']),
        )

    return response


def clear_auth_cookies[T: HttpResponse](response: T) -> T:
    """Clear JWT token cookies from the response"""
    jwt_settings = settings.SIMPLE_JWT
    response.delete_cookie(
        str(jwt_settings['AUTH_COOKIE']),
        path=str(jwt_settings['AUTH_COOKIE_PATH']),
        domain=str(jwt_settings['AUTH_COOKIE_DOMAIN']),
    )
    response.delete_cookie(
        str(jwt_settings['AUTH_COOKIE_REFRESH']),
        path=str(jwt_settings['AUTH_COOKIE_PATH']),
        domain=str(jwt_settings['AUTH_COOKIE_DOMAIN']),
    )
    return response


def get_token_from_cookie(request: HttpRequest | Request) -> str | None:
    """Get JWT token from cookie"""
    auth_cookie = str(settings.SIMPLE_JWT['AUTH_COOKIE'])
    return request.COOKIES.get(auth_cookie)


def get_refresh_token_from_cookie(
    request: HttpRequest | Request,
) -> str | None:
    """Get refresh token from cookie"""
    refresh_cookie = str(settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH'])
    return request.COOKIES.get(refresh_cookie)
