from django.contrib.auth.forms import (
    AuthenticationForm,
    ReadOnlyPasswordHashField,
    UserCreationForm,
)
from django.forms import CharField, ModelForm, PasswordInput
from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User


class UserLoginForm(AuthenticationForm):
    username = CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        label='Имя пользователя или Email',
    )
    password = CharField(
        label='Пароль',
        strip=False,
        widget=PasswordInput,
    )


class RegisterUserForm(UserCreationForm):
    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'password1',
            'password2',
        ]


class UpdateUserForm(ModelForm):
    password = ReadOnlyPasswordHashField(
        label='',
        help_text=constants.HELP_TEXT_PASSWORD,
    )

    class Meta:
        model = User
        fields = [
            'username',
        ]
