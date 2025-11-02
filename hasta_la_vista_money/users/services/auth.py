from typing import cast

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpRequest, HttpResponse
from rest_framework_simplejwt.tokens import RefreshToken
from typing_extensions import TypedDict

from hasta_la_vista_money.authentication.authentication import set_auth_cookies
from hasta_la_vista_money.users.models import User


class LoginResult(TypedDict, total=False):
    """Результат попытки входа пользователя."""

    user: User
    access: str | None
    refresh: str | None
    success: bool


def login_user(
    request: HttpRequest,
    form: AuthenticationForm,
    success_message: str,
) -> LoginResult:
    username = form.cleaned_data['username']
    password = form.cleaned_data['password']

    user = authenticate(
        request,
        username=username,
        password=password,
        backend='django.contrib.auth.backends.ModelBackend',
    )
    if user is not None:
        login(request, user)
        try:
            tokens = RefreshToken.for_user(user)
            jwt_access_token = str(tokens.access_token)
            jwt_refresh_token = str(tokens)
        except (ValueError, TypeError, AttributeError):
            jwt_access_token = None
            jwt_refresh_token = None

        messages.success(request, success_message)
        return {
            'user': cast('User', user),
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
    """Helper function to set JWT cookies in a response"""
    return set_auth_cookies(response, access_token, refresh_token)
