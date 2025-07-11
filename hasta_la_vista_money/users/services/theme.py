from hasta_la_vista_money.users.models import User


def set_user_theme(user: User, theme: str) -> bool:
    if theme not in ['light', 'dark']:
        theme = 'light'
    user.theme = theme
    user.save()
    return True
