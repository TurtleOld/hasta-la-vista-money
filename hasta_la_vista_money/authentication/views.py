from typing import Any, ClassVar

from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from hasta_la_vista_money.api.throttling import (
    AnonLoginRateThrottle,
    LoginRateThrottle,
)
from hasta_la_vista_money.authentication.authentication import (
    clear_auth_cookies,
    get_refresh_token_from_cookie,
    set_auth_cookies,
)
from hasta_la_vista_money.users.models import User


class SessionTokenObtainView(APIView):
    """Get JWT tokens based on Django session authentication"""

    permission_classes = (IsAuthenticated,)

    def _validate_user(self, user) -> None:
        if not isinstance(user, User):
            raise TypeError(_('Пользователь не авторизован'))

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            self._validate_user(request.user)
            refresh = RefreshToken.for_user(request.user)
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


class CookieTokenObtainPairView(TokenObtainPairView):
    """Custom token obtain view that sets HttpOnly cookies"""

    throttle_classes: ClassVar[list] = [
        AnonLoginRateThrottle,
        LoginRateThrottle,
    ]

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


class CookieTokenRefreshView(TokenRefreshView):
    """Custom token refresh view that works with HttpOnly cookies"""

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        refresh_token = get_refresh_token_from_cookie(request)

        if not refresh_token:
            response = Response(
                {'error': 'No refresh token found'},
                status=status.HTTP_400_BAD_REQUEST,
            )
            return clear_auth_cookies(response)

        try:
            serializer = self.get_serializer(data={'refresh': refresh_token})
            serializer.is_valid(raise_exception=True)
            refresh = serializer.validated_data

            response = Response({'success': True})
            response = set_auth_cookies(
                response,
                refresh['access'],
                refresh.get('refresh', refresh_token),
            )

        except InvalidToken:
            response = Response(
                {'error': 'Invalid refresh token'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)
        except (TypeError, ValueError, KeyError) as e:
            response = Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            return clear_auth_cookies(response)
        else:
            return response
