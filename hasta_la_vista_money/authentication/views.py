from typing import Any, cast

from django.contrib.auth.models import AnonymousUser
from django.utils.translation import gettext_lazy as _
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from hasta_la_vista_money.authentication.authentication import (
    clear_auth_cookies,
    get_refresh_token_from_cookie,
    set_auth_cookies,
)
from hasta_la_vista_money.users.models import User


@extend_schema(
    tags=['authentication'],
    summary='Получение JWT токенов из сессии',
    description='Получить JWT токены на основе Django session аутентификации',
    request=None,
    responses={
        200: OpenApiResponse(
            description='Токены успешно получены',
            response={
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                },
            },
        ),
        400: OpenApiResponse(description='Ошибка при получении токенов'),
    },
)
class SessionTokenObtainView(APIView):
    """Get JWT tokens based on Django session authentication"""

    schema = AutoSchema()
    permission_classes = (IsAuthenticated,)

    def _validate_user(self, user: User | AnonymousUser) -> None:
        if not isinstance(user, User):
            raise TypeError(_('Пользователь не авторизован'))

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            self._validate_user(request.user)
            user = cast('User', request.user)
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)
            refresh_token = str(refresh)

            response = Response({'success': True})
            return set_auth_cookies(response, access_token, refresh_token)

        except (TypeError, ValueError, KeyError) as e:
            response = Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
            return clear_auth_cookies(response)


@extend_schema(
    tags=['authentication'],
    summary='Получение JWT токенов',
    description=(
        'Получить access и refresh JWT токены. '
        'Токены возвращаются в JSON ответе и дополнительно устанавливаются '
        'в HttpOnly cookies для веб-клиентов.'
    ),
    responses={
        200: OpenApiResponse(
            description='Токены успешно получены',
            response={
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'access': {'type': 'string'},
                    'refresh': {'type': 'string'},
                },
            },
        ),
        400: OpenApiResponse(description='Ошибка валидации данных'),
        401: OpenApiResponse(description='Неверные учетные данные'),
    },
)
class CookieTokenObtainPairView(TokenObtainPairView):
    """Custom token obtain view that sets HttpOnly cookies and returns JSON"""

    schema = AutoSchema()

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            response = super().post(request, *args, **kwargs)

            if response.data:
                access_token = response.data.get('access')
                refresh_token = response.data.get('refresh')

                if access_token and refresh_token:
                    response = set_auth_cookies(
                        response,
                        access_token,
                        refresh_token,
                    )
                    response.data = {
                        'success': True,
                        'access': access_token,
                        'refresh': refresh_token,
                    }

        except (TypeError, ValueError, KeyError) as e:
            response = Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
            return clear_auth_cookies(response)
        else:
            return response


@extend_schema(
    tags=['authentication'],
    summary='Обновление JWT токена',
    description=(
        'Обновить access токен используя refresh токен. '
        'Refresh токен может быть передан в JSON body ({"refresh": "<token>"}) '
        'или в HttpOnly cookie. Приоритет: сначала JSON body, затем cookie. '
        'Ответ всегда содержит access и refresh в JSON. '
        'Cookies устанавливаются дополнительно для веб-клиентов.'
    ),
    responses={
        200: OpenApiResponse(
            description='Токены успешно обновлены',
            response={
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'access': {'type': 'string'},
                    'refresh': {'type': 'string'},
                },
            },
        ),
        400: OpenApiResponse(
            description='Refresh токен не найден (отсутствует в body и cookie)',
        ),
        401: OpenApiResponse(
            description='Невалидный или истёкший refresh токен',
        ),
    },
)
class CookieTokenRefreshView(TokenRefreshView):
    """Custom token refresh view that works with JSON body and cookies"""

    schema = AutoSchema()

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        refresh_token = None

        if hasattr(request, 'data') and request.data:
            refresh_token = request.data.get('refresh')

        if not refresh_token:
            refresh_token = get_refresh_token_from_cookie(request)

        if not refresh_token:
            error_msg = (
                'No refresh token found. '
                'Provide refresh in JSON body or cookie.'
            )
            response = Response(
                {'error': error_msg},
                status=status.HTTP_400_BAD_REQUEST,
            )
            return clear_auth_cookies(response)

        try:
            serializer = self.get_serializer(data={'refresh': refresh_token})
            serializer.is_valid(raise_exception=True)
            refresh = serializer.validated_data

            new_access = refresh['access']
            new_refresh = refresh.get('refresh', refresh_token)

            response = Response(
                {
                    'success': True,
                    'access': new_access,
                    'refresh': new_refresh,
                },
            )
            return set_auth_cookies(
                response,
                new_access,
                new_refresh,
            )

        except (InvalidToken, TokenError):
            response = Response(
                {'error': 'Invalid refresh token'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)
        except (TypeError, ValueError, KeyError) as e:
            response = Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
            return clear_auth_cookies(response)
