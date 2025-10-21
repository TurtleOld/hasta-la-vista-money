from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.users.forms import RegisterUserForm
from hasta_la_vista_money.users.services.registration import register_user

User = get_user_model()


class RegisterUserServiceTest(TestCase):
    """Tests for register_user service function."""

    def test_register_user(self):
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password1': 'StrongPassword123',
            'password2': 'StrongPassword123',
            'first_name': 'Test',
            'last_name': 'User',
        }
        form = RegisterUserForm(data=data)
        self.assertTrue(form.is_valid())
        user = register_user(form)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertEqual(user.username, 'newuser')
        self.assertEqual(user.email, 'newuser@example.com')
        self.assertTrue(user.date_joined <= timezone.now())
