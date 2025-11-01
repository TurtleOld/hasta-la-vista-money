from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm
from django.http import HttpRequest


def set_user_password(form: SetPasswordForm, request: HttpRequest) -> None:
    form.save()
    update_session_auth_hash(request=request, user=form.user)
