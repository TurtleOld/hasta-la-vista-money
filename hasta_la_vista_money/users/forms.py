from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import Group
from django.forms import (
    CharField,
    ModelForm,
    ModelMultipleChoiceField,
    PasswordInput,
)
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
            "username",
            "email",
            "first_name",
            "last_name",
        ]
        labels = {
            "username": "Имя пользователя",
            "email": "Email",
            "first_name": "Имя",
            "last_name": "Фамилия",
        }


class GroupCreateForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name']
        labels = {'name': 'Название группы'}


class GroupDeleteForm(forms.Form):
    group = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        label='Группа для удаления',
    )


class AddUserToGroupForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.all(), label='Пользователь')
    group = forms.ModelChoiceField(queryset=Group.objects.none(), label="Группа")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = None
        if self.is_bound and self.data.get("user"):
            try:
                user = User.objects.get(pk=self.data.get("user"))
            except (ValueError, User.DoesNotExist):
                user = None
        elif "user" in self.initial and self.initial["user"]:
            user_val = self.initial["user"]
            if isinstance(user_val, User):
                user = user_val
            else:
                try:
                    user = User.objects.get(pk=user_val)
                except (ValueError, User.DoesNotExist):
                    user = None
        if user:
            self.fields["group"].queryset = Group.objects.exclude(
                id__in=user.groups.values_list("id", flat=True)
            )
        else:
            self.fields["group"].queryset = Group.objects.none()


class DeleteUserFromGroupForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.all(), label='Пользователь')
    group = forms.ModelChoiceField(queryset=Group.objects.none(), label="Группа")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = None
        if self.is_bound and self.data.get("user"):
            try:
                user = User.objects.get(pk=self.data.get("user"))
            except (ValueError, User.DoesNotExist):
                user = None
        elif "user" in self.initial and self.initial["user"]:
            user_val = self.initial["user"]
            if isinstance(user_val, User):
                user = user_val
            else:
                try:
                    user = User.objects.get(pk=user_val)
                except (ValueError, User.DoesNotExist):
                    user = None
        if user:
            self.fields["group"].queryset = user.groups.all()
        else:
            self.fields["group"].queryset = Group.objects.none()
