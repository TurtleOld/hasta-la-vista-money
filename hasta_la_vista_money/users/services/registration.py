from hasta_la_vista_money.services.generate_dates import generate_date_list
from hasta_la_vista_money.users.forms import RegisterUserForm
from hasta_la_vista_money.users.models import User


def register_user(form: RegisterUserForm) -> User:
    user = form.save(commit=False)
    user.is_superuser = True
    user.is_staff = True
    user.save()
    form.save_m2m()
    generate_date_list(user.date_joined, user)
    return user
