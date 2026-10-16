"""User password service.

This module provides services for managing user passwords.
"""

from typing import Any

from django.contrib.auth import update_session_auth_hash
from django.http import HttpRequest
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from hasta_la_vista_money.users.models import User


def blacklist_user_refresh_tokens(user: User) -> None:
    """Revoke all outstanding refresh tokens of the user."""
    BlacklistedToken.objects.bulk_create(
        [
            BlacklistedToken(token=token)
            for token in OutstandingToken.objects.filter(
                user=user,
                blacklistedtoken__isnull=True,
            )
        ],
        ignore_conflicts=True,
    )


def set_user_password(form: Any, request: HttpRequest) -> None:
    """Set user password, update session and revoke refresh tokens.

    Args:
        form: Validated password change form.
        request: HTTP request object.
    """
    form.save()
    blacklist_user_refresh_tokens(form.user)
    update_session_auth_hash(request=request, user=form.user)
