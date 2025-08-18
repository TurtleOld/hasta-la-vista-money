from typing import Optional, TypeVar, Union, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.users.models import User
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import Token

T = TypeVar('T', bound=HttpResponse)


class CookieJWTAuthentication(JWTAuthentication):
    """Custom JWT authentication that uses HttpOnly cookies instead of Authorization header"""

    def authenticate(self, request: Request) -> Optional[tuple[User, Token]]:  # type: ignore[override]
        header = self.get_header(request)
        raw_token = None

        if header is not None:
            raw_token = self.get_raw_token(header)

        if raw_token is None:
            cookie_token = request.COOKIES.get(str(settings.SIMPLE_JWT['AUTH_COOKIE']))
            if cookie_token is None:
                return None
            raw_token = cookie_token.encode('utf-8')

        try:
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)

            if not isinstance(user, User):
                raise ValueError(
                    _('Ожидался экземпляр User, получен {type_name}').format(
                        type_name=type(user),
                    ),
                )

            return user, validated_token
        except Exception:
            return None

    def authenticate_header(self, request: Request) -> str:
        return 'Bearer realm="api"'


def set_auth_cookies(
    response: T,
    access_token: str,
    refresh_token: str | None = None,
) -> T:
    """Set JWT tokens as HttpOnly cookies in the response"""
    jwt_settings = settings.SIMPLE_JWT
    response.set_cookie(
        str(jwt_settings['AUTH_COOKIE']),
        access_token,
        max_age=(
            cast(int, jwt_settings['AUTH_COOKIE_MAX_AGE'])
            if jwt_settings['AUTH_COOKIE_MAX_AGE'] is not None
            else None
        ),
        domain=str(jwt_settings['AUTH_COOKIE_DOMAIN']),
        secure=bool(jwt_settings['AUTH_COOKIE_SECURE']),
        httponly=bool(jwt_settings['AUTH_COOKIE_HTTP_ONLY']),
        samesite=cast(str, jwt_settings['AUTH_COOKIE_SAMESITE'])
        if jwt_settings['AUTH_COOKIE_SAMESITE']
        else None,  # type: ignore[arg-type]
        path=str(jwt_settings['AUTH_COOKIE_PATH']),
    )
    if refresh_token:
        response.set_cookie(
            str(jwt_settings['AUTH_COOKIE_REFRESH']),
            refresh_token,
            max_age=(
                cast(int, jwt_settings['AUTH_COOKIE_REFRESH_MAX_AGE'])
                if jwt_settings['AUTH_COOKIE_REFRESH_MAX_AGE'] is not None
                else None
            ),
            domain=str(jwt_settings['AUTH_COOKIE_DOMAIN']),
            secure=bool(jwt_settings['AUTH_COOKIE_SECURE']),
            httponly=bool(jwt_settings['AUTH_COOKIE_HTTP_ONLY']),
            samesite=cast(str, jwt_settings['AUTH_COOKIE_SAMESITE'])
            if jwt_settings['AUTH_COOKIE_SAMESITE']
            else None,  # type: ignore[arg-type]
            path=str(jwt_settings['AUTH_COOKIE_PATH']),
        )

    return response


def clear_auth_cookies(response: T) -> T:
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


def get_token_from_cookie(request: Union[HttpRequest, Request]) -> str | None:
    """Get JWT token from cookie"""
    auth_cookie = str(settings.SIMPLE_JWT['AUTH_COOKIE'])
    return request.COOKIES.get(auth_cookie)


def get_refresh_token_from_cookie(request: Union[HttpRequest, Request]) -> str | None:
    """Get refresh token from cookie"""
    refresh_cookie = str(settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH'])
    return request.COOKIES.get(refresh_cookie)
