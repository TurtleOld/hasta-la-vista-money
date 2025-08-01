from typing import Any, Dict

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpRequest
from hasta_la_vista_money.authentication.authentication import set_auth_cookies
from rest_framework_simplejwt.tokens import RefreshToken


def login_user(
    request: HttpRequest,
    form: AuthenticationForm,
    success_message: str,
) -> Dict[str, Any]:
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
        tokens = RefreshToken.for_user(user)
        jwt_access_token = str(tokens.access_token)
        jwt_refresh_token = str(tokens)
        messages.success(request, success_message)
        return {
            'user': user,
            'access': jwt_access_token,
            'refresh': jwt_refresh_token,
            'success': True,
        }
    else:
        return {'success': False}


def set_auth_cookies_in_response(response, access_token, refresh_token=None):
    """Helper function to set JWT cookies in a response"""
    return set_auth_cookies(response, access_token, refresh_token)
