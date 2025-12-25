"""User profile service.

This module provides services for updating user profile information.
"""

from hasta_la_vista_money.users.forms import UpdateUserForm
from hasta_la_vista_money.users.models import User


def update_user_profile(form: UpdateUserForm) -> User:
    """Update user profile from form.

    Args:
        form: Validated user profile form.

    Returns:
        Updated User instance.
    """
    user = form.save(commit=False)
    user.save()
    form.save_m2m()
    return user
