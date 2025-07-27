from hasta_la_vista_money.authentication.authentication import (
    clear_auth_cookies,
    get_refresh_token_from_cookie,
    set_auth_cookies,
)
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)


class SessionTokenObtainView(APIView):
    """Get JWT tokens based on Django session authentication"""

    permission_classes = (IsAuthenticated,)

    def post(self, request, *args, **kwargs):
        try:
            # Generate new tokens for the authenticated user
            refresh = RefreshToken.for_user(request.user)
            access_token = str(refresh.access_token)
            refresh_token = str(refresh)

            response = Response({'success': True})
            response = set_auth_cookies(response, access_token, refresh_token)

            return response

        except Exception as e:
            response = Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            return clear_auth_cookies(response)


class CookieTokenObtainPairView(TokenObtainPairView):
    """Custom token obtain view that sets HttpOnly cookies"""

    def post(self, request, *args, **kwargs):
        try:
            # Get tokens using the parent class method
            response = super().post(request, *args, **kwargs)

            # Set tokens as HttpOnly cookies
            if response.data:
                access_token = response.data.get('access')
                refresh_token = response.data.get('refresh')

                if access_token and refresh_token:
                    response = set_auth_cookies(response, access_token, refresh_token)
                    response.data = {'success': True}

            return response

        except Exception as e:
            response = Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            return clear_auth_cookies(response)


class CookieTokenRefreshView(TokenRefreshView):
    """Custom token refresh view that works with HttpOnly cookies"""

    def post(self, request, *args, **kwargs):
        refresh_token = get_refresh_token_from_cookie(request)

        if not refresh_token:
            response = Response(
                {'error': 'No refresh token found'},
                status=status.HTTP_400_BAD_REQUEST,
            )
            return clear_auth_cookies(response)

        try:
            refresh = self.get_serializer().validate({'refresh': refresh_token})

            response = Response({'success': True})
            response = set_auth_cookies(
                response,
                refresh['access'],
                refresh.get('refresh', refresh_token),
            )

            return response

        except InvalidToken:
            response = Response(
                {'error': 'Invalid refresh token'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            return clear_auth_cookies(response)
        except Exception as e:
            response = Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            return clear_auth_cookies(response)
