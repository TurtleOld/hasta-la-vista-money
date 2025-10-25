from typing import ClassVar

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest
from django.test import RequestFactory, TestCase

from hasta_la_vista_money.users.services.auth import login_user

User = get_user_model()


class LoginUserServiceTest(TestCase):
    """Tests for login_user service function."""

    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self) -> None:
        self.factory = RequestFactory()
        user = User.objects.first()
        if user is None:
            error_msg = 'No user found in fixtures'
            raise ValueError(error_msg)
        self.user = user
        self.user.set_password('testpassword')
        self.user.save()

    def get_request(self) -> HttpRequest:
        request = self.factory.post('/login/')
        SessionMiddleware(lambda: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda: None).process_request(request)
        return request

    def test_login_user_success(self) -> None:
        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()  # populates cleaned_data
        result = login_user(request, form, 'Success!')
        self.assertTrue(result['success'])
        self.assertIn('access', result)
        self.assertIn('refresh', result)
        self.assertEqual(result['user'], self.user)

    def test_login_user_failure(self) -> None:
        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'wrongpassword',
            },
        )
        form.is_valid()
        result = login_user(request, form, 'Fail!')
        self.assertFalse(result['success'])
