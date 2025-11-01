from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.users.forms import RegisterUserForm
from hasta_la_vista_money.users.services.registration import register_user

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class RegisterUserServiceTest(TestCase):
    """Tests for register_user service function."""

    def test_register_user(self) -> None:
        data: dict[str, str] = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password1': 'StrongPassword123',
            'password2': 'StrongPassword123',
            'first_name': 'Test',
            'last_name': 'User',
        }
        form: RegisterUserForm = RegisterUserForm(data=data)
        self.assertTrue(form.is_valid())
        user: UserType = register_user(form)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertEqual(user.username, 'newuser')
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertTrue(user.date_joined <= timezone.now())
