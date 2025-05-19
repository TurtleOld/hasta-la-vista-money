from django.contrib.auth.forms import (
    AuthenticationForm,
    ReadOnlyPasswordHashField,
    UserCreationForm,
)
from django.forms import CharField, ModelForm, PasswordInput
from django_stubs_ext.db.models import TypedModelMeta
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


class RegisterUserForm(UserCreationForm[User]):
    class Meta(TypedModelMeta):
        model = User
        fields = [
            'username',
            'email',
            'password1',
            'password2',
        ]


class UpdateUserForm(ModelForm):
    class Meta:
        model = User
        fields = [
            'username',
        ]
