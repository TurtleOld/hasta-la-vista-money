from django.contrib.auth import authenticate, login
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib import messages


def login_user(request, form, success_message):
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
        messages.error(request, 'Неправильный логин или пароль!')
        return {'success': False}
