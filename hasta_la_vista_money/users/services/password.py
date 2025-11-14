from typing import Any

from django.contrib.auth import update_session_auth_hash
from django.http import HttpRequest


def set_user_password(form: Any, request: HttpRequest) -> None:
    form.save()
    update_session_auth_hash(request=request, user=form.user)
