from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.services.generate_dates import generate_date_list


def register_user(form) -> User:
    user = form.save(commit=False)
    user.is_superuser = True
    user.is_staff = True
    user.save()
    form.save_m2m()
    generate_date_list(user.date_joined, user)
    return user
