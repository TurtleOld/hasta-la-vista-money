from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.forms import CharField, ModelForm, PasswordInput, ModelMultipleChoiceField
from django_stubs_ext.db.models import TypedModelMeta
from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User
from django.contrib.auth.models import Group
from django import forms


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
    groups = ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        label="Группы",
        widget=None,  # Можно заменить на CheckboxSelectMultiple или другой виджет при необходимости
    )
    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "groups",
        ]
        labels = {
            "username": "Имя пользователя",
            "email": "Email",
            "first_name": "Имя",
            "last_name": "Фамилия",
            "groups": "Группы",
        }


class GroupCreateForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name"]
        labels = {"name": "Название группы"}


class GroupDeleteForm(forms.Form):
    group = forms.ModelChoiceField(
        queryset=Group.objects.all(), label="Группа для удаления"
    )


class AddUserToGroupForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.all(), label="Пользователь")
    group = forms.ModelChoiceField(queryset=Group.objects.all(), label="Группа")
