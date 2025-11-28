from typing import Any, ClassVar

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import Group
from django.forms import CharField, ModelForm, PasswordInput
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from django_stubs_ext.db.models import TypedModelMeta

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.groups import (
    add_user_to_group,
    remove_user_from_group,
)


class UserLoginForm(AuthenticationForm):
    """Form for user authentication using username or email."""

    username: CharField

    username = CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        label=_('Имя пользователя или Email'),
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
            },
        ),
        error_messages={
            'required': _('Пожалуйста, введите имя пользователя или email.'),
        },
    )
    password = CharField(
        label=_('Пароль'),
        strip=False,
        widget=PasswordInput(
            attrs={
                'class': 'form-control',
            },
        ),
        error_messages={
            'required': _('Пожалуйста, введите пароль.'),
        },
    )


class RegisterUserForm(UserCreationForm[User]):
    """Form for creating new user accounts."""

    class Meta(TypedModelMeta):
        model: ClassVar[type[User]] = User
        fields: ClassVar[list[str]] = [
            'username',
            'email',
            'password1',
            'password2',
        ]
        widgets: ClassVar[dict[str, Any]] = {
            'username': forms.TextInput(
                attrs={
                    'placeholder': _('Имя пользователя'),
                    'class': 'form-control',
                },
            ),
            'email': forms.EmailInput(
                attrs={
                    'placeholder': _('Email'),
                    'class': 'form-control',
                },
            ),
        }
        help_texts: ClassVar[dict[str, Any]] = {
            'username': _('Только буквы, цифры и @/./+/-/_'),
            'email': _('Укажите действующий email.'),
        }
        error_messages: ClassVar[dict[str, dict[str, Any]]] = {
            'username': {
                'required': _('Пожалуйста, введите имя пользователя.'),
            },
            'email': {
                'required': _('Пожалуйста, введите email.'),
            },
        }


class UpdateUserForm(ModelForm[User]):
    """Form for updating user profile information."""

    class Meta:
        model: ClassVar[type[User]] = User
        fields: ClassVar[list[str]] = [
            'username',
            'email',
            'first_name',
            'last_name',
        ]
        labels: ClassVar[dict[str, Any]] = {
            'username': _('Имя пользователя'),
            'email': _('Email'),
            'first_name': _('Имя'),
            'last_name': _('Фамилия'),
        }
        widgets: ClassVar[dict[str, Any]] = {
            'username': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Имя пользователя'),
                },
            ),
            'email': forms.EmailInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Email'),
                },
            ),
            'first_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Имя'),
                },
            ),
            'last_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Фамилия'),
                },
            ),
        }
        help_texts: ClassVar[dict[str, Any]] = {
            'username': _('Только буквы, цифры и @/./+/-/_'),
            'email': _('Укажите действующий email.'),
            'first_name': _('Ваше имя.'),
            'last_name': _('Ваша фамилия.'),
        }
        error_messages: ClassVar[dict[str, dict[str, Any]]] = {
            'username': {
                'required': _('Пожалуйста, введите имя пользователя.'),
            },
            'email': {
                'required': _('Пожалуйста, введите email.'),
            },
        }


class GroupCreateForm(ModelForm[Group]):
    """Form for creating new user groups."""

    class Meta:
        model: ClassVar[type[Group]] = Group
        fields: ClassVar[list[str]] = ['name']
        labels: ClassVar[dict[str, Any]] = {'name': _('Название группы')}
        widgets: ClassVar[dict[str, Any]] = {
            'name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Название группы'),
                },
            ),
        }
        help_texts: ClassVar[dict[str, Any]] = {
            'name': _('Введите уникальное название группы.'),
        }
        error_messages: ClassVar[dict[str, dict[str, Any]]] = {
            'name': {
                'required': _('Пожалуйста, введите название группы.'),
            },
        }


class GroupDeleteForm(forms.Form):
    """Form for deleting user groups."""

    group: forms.ModelChoiceField[Group]
    group = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        label=_('Группа для удаления'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text=_('Выберите группу для удаления.'),
        error_messages={
            'required': _('Пожалуйста, выберите группу.'),
        },
    )


class UserGroupBaseForm(forms.Form):
    """Base form for user-group operations."""

    user: forms.ModelChoiceField[User]
    group: forms.ModelChoiceField[Group]
    user_instance: User | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user_instance = self._get_user_instance()

    def _get_user_instance(self) -> User | None:
        """Extract User instance from form data or initial data."""
        user_id = self.data.get('user')
        if user_id:
            try:
                return User.objects.get(pk=user_id)
            except User.DoesNotExist:
                pass
        initial_user = self.initial.get('user')
        if initial_user:
            try:
                return User.objects.get(pk=initial_user)
            except User.DoesNotExist:
                pass
        return None

    user = forms.ModelChoiceField(
        queryset=User.objects.all(),
        label=_('Пользователь'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text=_('Выберите пользователя.'),
        error_messages={
            'required': _('Пожалуйста, выберите пользователя.'),
        },
    )
    group = forms.ModelChoiceField(
        queryset=Group.objects.none(),
        label=_('Группа'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text=_('Выберите группу.'),
        error_messages={
            'required': _('Пожалуйста, выберите группу.'),
        },
    )


class AddUserToGroupForm(UserGroupBaseForm):
    """Form for adding users to groups."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.user_instance:
            self.fields['group'].queryset = Group.objects.exclude(  # type: ignore[attr-defined]
                id__in=self.user_instance.groups.values_list('id', flat=True),
            )
        else:
            self.fields['group'].queryset = Group.objects.none()  # type: ignore[attr-defined]

    def save(self, request: HttpRequest) -> None:
        """Add user to selected group."""
        add_user_to_group(
            request,
            self.cleaned_data['user'],
            self.cleaned_data['group'],
        )


class DeleteUserFromGroupForm(UserGroupBaseForm):
    """Form for removing users from groups."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.user_instance:
            self.fields['group'].queryset = self.user_instance.groups.all()  # type: ignore[attr-defined]
        else:
            self.fields['group'].queryset = Group.objects.none()  # type: ignore[attr-defined]

    def save(self, request: HttpRequest) -> None:
        """Remove user from selected group."""
        remove_user_from_group(
            request,
            self.cleaned_data['user'],
            self.cleaned_data['group'],
        )
