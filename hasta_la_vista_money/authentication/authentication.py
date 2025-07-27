from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """Custom JWT authentication that uses HttpOnly cookies instead of Authorization header"""

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            # Try to get token from cookie
            raw_token = request.COOKIES.get(settings.SIMPLE_JWT['AUTH_COOKIE'])
            if raw_token is None:
                return None
        else:
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token

    def authenticate_header(self, request):
        return 'Bearer realm="api"'


def set_auth_cookies(response, access_token, refresh_token=None):
    """Set JWT tokens as HttpOnly cookies in the response"""
    from django.conf import settings

    jwt_settings = settings.SIMPLE_JWT

    # Set access token cookie
    response.set_cookie(
        jwt_settings['AUTH_COOKIE'],
        access_token,
        max_age=jwt_settings['AUTH_COOKIE_MAX_AGE'],
        domain=jwt_settings['AUTH_COOKIE_DOMAIN'],
        secure=jwt_settings['AUTH_COOKIE_SECURE'],
        httponly=jwt_settings['AUTH_COOKIE_HTTP_ONLY'],
        samesite=jwt_settings['AUTH_COOKIE_SAMESITE'],
        path=jwt_settings['AUTH_COOKIE_PATH'],
    )

    # Set refresh token cookie if provided
    if refresh_token:
        response.set_cookie(
            jwt_settings['AUTH_COOKIE_REFRESH'],
            refresh_token,
            max_age=jwt_settings['AUTH_COOKIE_REFRESH_MAX_AGE'],
            domain=jwt_settings['AUTH_COOKIE_DOMAIN'],
            secure=jwt_settings['AUTH_COOKIE_SECURE'],
            httponly=jwt_settings['AUTH_COOKIE_HTTP_ONLY'],
            samesite=jwt_settings['AUTH_COOKIE_SAMESITE'],
            path=jwt_settings['AUTH_COOKIE_PATH'],
        )

    return response


def clear_auth_cookies(response):
    """Clear JWT token cookies from the response"""
    from django.conf import settings

    jwt_settings = settings.SIMPLE_JWT

    # Clear access token cookie
    response.delete_cookie(
        jwt_settings['AUTH_COOKIE'],
        path=jwt_settings['AUTH_COOKIE_PATH'],
        domain=jwt_settings['AUTH_COOKIE_DOMAIN'],
    )

    # Clear refresh token cookie
    response.delete_cookie(
        jwt_settings['AUTH_COOKIE_REFRESH'],
        path=jwt_settings['AUTH_COOKIE_PATH'],
        domain=jwt_settings['AUTH_COOKIE_DOMAIN'],
    )

    return response


def get_token_from_cookie(request):
    """Get JWT token from cookie"""
    from django.conf import settings

    return request.COOKIES.get(settings.SIMPLE_JWT['AUTH_COOKIE'])


def get_refresh_token_from_cookie(request):
    """Get refresh token from cookie"""
    from django.conf import settings

    return request.COOKIES.get(settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH'])
