from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm


def set_user_password(form: SetPasswordForm, request) -> None:
    form.save()
    update_session_auth_hash(request=request, user=form.user)
