from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpRequest, HttpResponse
from rest_framework_simplejwt.tokens import RefreshToken
from typing_extensions import TypedDict

from hasta_la_vista_money.authentication.authentication import set_auth_cookies
from hasta_la_vista_money.users.models import User


class LoginResult(TypedDict, total=False):
    """User login attempt result.

    Attributes:
        user: Authenticated user instance.
        access: JWT access token.
        refresh: JWT refresh token.
        success: Whether login was successful.
    """

    user: User
    access: str
    refresh: str
    success: bool


def login_user(
    request: HttpRequest,
    form: AuthenticationForm,
    success_message: str,
) -> LoginResult:
    """Authenticate and login user.

    Args:
        request: HTTP request object.
        form: Validated authentication form.
        success_message: Success message to display.

    Returns:
        LoginResult with user, tokens, and success status.
    """
    username = form.cleaned_data['username']
    password = form.cleaned_data['password']

    user = authenticate(
        request,
        username=username,
        password=password,
        backend='django.contrib.auth.backends.ModelBackend',
    )
    if user is not None and isinstance(user, User):
        login(request, user)
        try:
            tokens = RefreshToken.for_user(user)
            jwt_access_token = str(tokens.access_token)
            jwt_refresh_token = str(tokens)
        except (ValueError, TypeError, AttributeError):
            jwt_access_token = ''
            jwt_refresh_token = ''

        messages.success(request, success_message)
        return {
            'user': user,
            'access': jwt_access_token,
            'refresh': jwt_refresh_token,
            'success': True,
        }
    return {'success': False}


def set_auth_cookies_in_response(
    response: HttpResponse,
    access_token: str,
    refresh_token: str | None = None,
) -> HttpResponse:
    """Set JWT cookies in HTTP response.

    Args:
        response: HTTP response object.
        access_token: JWT access token.
        refresh_token: Optional JWT refresh token.

    Returns:
        HttpResponse with JWT cookies set.
    """
    return set_auth_cookies(response, access_token, refresh_token)
