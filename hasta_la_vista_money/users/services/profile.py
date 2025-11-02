from typing import cast

from hasta_la_vista_money.users.forms import UpdateUserForm
from hasta_la_vista_money.users.models import User


def update_user_profile(form: UpdateUserForm) -> User:
    user = form.save(commit=False)
    user.save()
    form.save_m2m()
    return cast('User', user)
