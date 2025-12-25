"""User theme service.

This module provides services for managing user interface themes.
"""

from hasta_la_vista_money.users.models import User


def set_user_theme(user: User, theme: str) -> bool:
    """Set user interface theme.

    Args:
        user: User to set theme for.
        theme: Theme name ('light' or 'dark'). Defaults to 'light'
            if invalid.

    Returns:
        True if theme was set successfully.
    """
    if theme not in ['light', 'dark']:
        theme = 'light'
    user.theme = theme
    user.save()
    return True
