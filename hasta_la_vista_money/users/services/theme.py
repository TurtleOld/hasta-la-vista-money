"""User theme service.

This module provides services for managing user interface themes.
"""

from hasta_la_vista_money.users.models import User

VALID_THEMES = {'light', 'dark', 'auto'}


def set_user_theme(user: User, theme: str) -> bool:
    """Set user interface theme.

    Args:
        user: User to set theme for.
        theme: Theme name ('light', 'dark' or 'auto'). Defaults to 'auto'
            if invalid.

    Returns:
        True if theme was set successfully.
    """
    if theme not in VALID_THEMES:
        theme = 'auto'
    user.theme = theme
    user.save()
    return True
