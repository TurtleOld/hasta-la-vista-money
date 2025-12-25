"""User password service.

This module provides services for managing user passwords.
"""

from typing import Any

from django.contrib.auth import update_session_auth_hash
from django.http import HttpRequest


def set_user_password(form: Any, request: HttpRequest) -> None:
    """Set user password and update session.

    Args:
        form: Validated password change form.
        request: HTTP request object.
    """
    form.save()
    update_session_auth_hash(request=request, user=form.user)
