from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import Group
from django.forms import (
    CharField,
    ModelForm,
    PasswordInput,
)
from django_stubs_ext.db.models import TypedModelMeta
from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User
from django.utils.translation import gettext_lazy as _
from typing import Any, Optional
from hasta_la_vista_money.users.services.groups import (
    add_user_to_group,
    remove_user_from_group,
)
from hasta_la_vista_money.users.validators import validate_username_unique
from django.http import HttpRequest


class UserLoginForm(AuthenticationForm):
    """
    Authentication form for user login by username or email.
    """

    username: CharField
    password: CharField

    username = CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        label=_('Имя пользователя или Email'),
        widget=forms.TextInput(
            attrs={
                'placeholder': _('Имя пользователя или Email'),
                'class': 'form-control',
            }
        ),
        help_text=_('Введите имя пользователя или email.'),
        error_messages={
            'required': _('Пожалуйста, введите имя пользователя или email.'),
        },
    )
    password = CharField(
        label=_('Пароль'),
        strip=False,
        widget=PasswordInput(
            attrs={
                'placeholder': _('Пароль'),
                'class': 'form-control',
            }
        ),
        help_text=_('Введите ваш пароль.'),
        error_messages={
            'required': _('Пожалуйста, введите пароль.'),
        },
    )


class RegisterUserForm(UserCreationForm[User]):
    """
    User registration form.
    """

    # Example: add custom validator for username
    def clean_username(self):
        username = self.cleaned_data.get('username')
        validate_username_unique(username)
        return username

    class Meta(TypedModelMeta):
        model = User
        fields = [
            'username',
            'email',
            'password1',
            'password2',
        ]
        widgets = {
            'username': forms.TextInput(
                attrs={
                    'placeholder': _('Имя пользователя'),
                    'class': 'form-control',
                }
            ),
            'email': forms.EmailInput(
                attrs={
                    'placeholder': _('Email'),
                    'class': 'form-control',
                }
            ),
        }
        help_texts = {
            'username': _('Только буквы, цифры и @/./+/-/_'),
            'email': _('Укажите действующий email.'),
        }
        error_messages = {
            'username': {
                'required': _('Пожалуйста, введите имя пользователя.'),
            },
            'email': {
                'required': _('Пожалуйста, введите email.'),
            },
        }


class UpdateUserForm(ModelForm):
    """
    Form for updating user profile information.
    """

    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'first_name',
            'last_name',
        ]
        labels = {
            'username': _('Имя пользователя'),
            'email': _('Email'),
            'first_name': _('Имя'),
            'last_name': _('Фамилия'),
        }
        widgets = {
            'username': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Имя пользователя'),
                }
            ),
            'email': forms.EmailInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Email'),
                }
            ),
            'first_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Имя'),
                }
            ),
            'last_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Фамилия'),
                }
            ),
        }
        help_texts = {
            'username': _('Только буквы, цифры и @/./+/-/_'),
            'email': _('Укажите действующий email.'),
            'first_name': _('Ваше имя.'),
            'last_name': _('Ваша фамилия.'),
        }
        error_messages = {
            'username': {
                'required': _('Пожалуйста, введите имя пользователя.'),
            },
            'email': {
                'required': _('Пожалуйста, введите email.'),
            },
        }


class GroupCreateForm(ModelForm):
    """
    Form for creating a new group.
    """

    class Meta:
        model = Group
        fields = ['name']
        labels = {'name': _('Название группы')}
        widgets = {
            'name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': _('Название группы'),
                }
            )
        }
        help_texts = {
            'name': _('Введите уникальное название группы.'),
        }
        error_messages = {
            'name': {
                'required': _('Пожалуйста, введите название группы.'),
            },
        }


class GroupDeleteForm(forms.Form):
    """
    Form for deleting a group.
    """

    group: forms.ModelChoiceField
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
    """
    Base form for user-group operations. Handles user instance extraction from data or initial.
    """

    user: forms.ModelChoiceField
    group: forms.ModelChoiceField
    user_instance: Optional[User] = None  # Ensure attribute always exists

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user_instance = self._get_user_instance()

    def _get_user_instance(self) -> Optional[User]:
        """
        Extracts the User instance from the form's data or initial data.
        """
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
    """
    Form for adding a user to a group. Group queryset excludes groups the user is already in.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.user_instance:
            self.fields['group'].queryset = Group.objects.exclude(
                id__in=self.user_instance.groups.values_list('id', flat=True)
            )
        else:
            self.fields['group'].queryset = Group.objects.none()

    def save(self, request: HttpRequest) -> None:
        """
        Calls the service to add the user to the group, passing request for messages.
        """
        add_user_to_group(
            request, self.cleaned_data['user'], self.cleaned_data['group']
        )


class DeleteUserFromGroupForm(UserGroupBaseForm):
    """
    Form for removing a user from a group. Group queryset is limited to user's groups.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.user_instance:
            self.fields['group'].queryset = self.user_instance.groups.all()
        else:
            self.fields['group'].queryset = Group.objects.none()

    def save(self, request: HttpRequest) -> None:
        """
        Calls the service to remove the user from the group, passing request for messages.
        """
        remove_user_from_group(
            request, self.cleaned_data['user'], self.cleaned_data['group']
        )
