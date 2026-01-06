from typing import Literal, ParamSpec, TypeVar, cast

import structlog
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
            result = self._authenticate_from_cookie(cookie_token, request)
            if result is not None:
                return result

        return self._authenticate_from_header(request)

    def _authenticate_from_cookie(
        self,
        cookie_token: str,
        request: Request,
    ) -> tuple[User, Token] | None:
        logger = structlog.get_logger(__name__)
        try:
            raw_token = cookie_token.encode('utf-8')
            validated_token = self.get_validated_token(raw_token)
            user = self.get_user(validated_token)

            if not isinstance(user, User):
                self._raise_invalid_user_type(user)
                return None
            return user, validated_token
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
        ) as e:
            logger.warning(
                ('Cookie token validation failed, trying Authorization header'),
                error=str(e),
                path=request.path,
            )
            return None

    def _authenticate_from_header(
        self,
        request: Request,
    ) -> tuple[User, Token] | None:
        logger = structlog.get_logger(__name__)
        header = self.get_header(request)
        if header is None:
            auth_header_raw = request.META.get(
                'HTTP_AUTHORIZATION',
            ) or request.META.get('Authorization')
            if auth_header_raw and auth_header_raw.startswith('Bearer '):
                header = auth_header_raw
            else:
                logger.warning(
                    'Authorization header not found by get_header',
                    path=request.path,
                    has_auth_meta_key='HTTP_AUTHORIZATION' in request.META
                    or 'Authorization' in request.META,
                    auth_header_present=auth_header_raw is not None,
                    auth_header_prefix=auth_header_raw[:30]
                    if auth_header_raw
                    else None,
                    all_meta_keys_with_auth=[
                        k for k in request.META if 'AUTH' in k.upper()
                    ],
                )
                return None
        raw_token_raw = self.get_raw_token(header)
        if raw_token_raw is None:
            logger.warning(
                'Failed to extract raw token from header',
                path=request.path,
                header_prefix=header[:50] if header else None,
            )
            return None

        try:
            validated_token = self.get_validated_token(raw_token_raw)
            user = self.get_user(validated_token)

            if not isinstance(user, User):
                self._raise_invalid_user_type(user)
                return None
            return user, validated_token
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
        ) as e:
            logger.warning(
                'Authorization header token validation failed',
                error=str(e),
                error_type=type(e).__name__,
                path=request.path,
            )
            return None

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
