from typing import ClassVar
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase

from hasta_la_vista_money.users.services.auth import (
    login_user,
    set_auth_cookies_in_response,
)

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
        form.is_valid()
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

    def test_login_user_nonexistent_user(self) -> None:
        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': 'nonexistent_user',
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result = login_user(request, form, 'Fail!')
        self.assertFalse(result['success'])

    def test_login_user_inactive_user(self) -> None:
        self.user.is_active = False
        self.user.save()

        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result = login_user(request, form, 'Fail!')
        self.assertFalse(result['success'])

    @patch('hasta_la_vista_money.users.services.auth.RefreshToken')
    def test_login_user_jwt_token_generation_success(
        self,
        mock_refresh_token,
    ) -> None:
        mock_token_instance = MagicMock()
        mock_token_instance.access_token = 'mock_access_token'
        mock_token_instance.__str__ = MagicMock(
            return_value='mock_refresh_token',
        )
        mock_refresh_token.for_user.return_value = mock_token_instance

        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result = login_user(request, form, 'Success!')

        self.assertTrue(result['success'])
        self.assertEqual(result['access'], 'mock_access_token')
        self.assertEqual(result['refresh'], 'mock_refresh_token')

    @patch('hasta_la_vista_money.users.services.auth.RefreshToken')
    def test_login_user_jwt_token_generation_failure(
        self, mock_refresh_token
    ) -> None:
        mock_refresh_token.for_user.side_effect = ValueError(
            'Token generation failed'
        )

        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result = login_user(request, form, 'Success!')

        self.assertTrue(result['success'])
        self.assertIsNone(result['access'])
        self.assertIsNone(result['refresh'])

    @patch('hasta_la_vista_money.users.services.auth.RefreshToken')
    def test_login_user_jwt_token_type_error(self, mock_refresh_token) -> None:
        mock_refresh_token.for_user.side_effect = TypeError('Type error')

        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result = login_user(request, form, 'Success!')

        self.assertTrue(result['success'])
        self.assertIsNone(result['access'])
        self.assertIsNone(result['refresh'])

    @patch('hasta_la_vista_money.users.services.auth.RefreshToken')
    def test_login_user_jwt_token_attribute_error(
        self, mock_refresh_token
    ) -> None:
        mock_refresh_token.for_user.side_effect = AttributeError(
            'Attribute error'
        )

        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result = login_user(request, form, 'Success!')

        self.assertTrue(result['success'])
        self.assertIsNone(result['access'])
        self.assertIsNone(result['refresh'])

    def test_login_user_empty_form_data(self) -> None:
        request = self.get_request()
        form = AuthenticationForm(request, data={})
        form.is_valid()

        with self.assertRaises(KeyError):
            login_user(request, form, 'Fail!')

    def test_login_user_missing_username(self) -> None:
        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={'password': 'testpassword'},
        )
        form.is_valid()

        with self.assertRaises(KeyError):
            login_user(request, form, 'Fail!')

    def test_login_user_missing_password(self) -> None:
        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={'username': str(self.user.get_username())},
        )
        form.is_valid()

        with self.assertRaises(KeyError):
            login_user(request, form, 'Fail!')


class SetAuthCookiesInResponseTest(TestCase):
    """Tests for set_auth_cookies_in_response helper function."""

    def setUp(self) -> None:
        self.factory = RequestFactory()

    @patch('hasta_la_vista_money.users.services.auth.set_auth_cookies')
    def test_set_auth_cookies_in_response_with_refresh_token(
        self,
        mock_set_auth_cookies,
    ) -> None:
        response = HttpResponse()
        access_token = 'test_access_token'
        refresh_token = 'test_refresh_token'

        mock_set_auth_cookies.return_value = response

        result = set_auth_cookies_in_response(
            response, access_token, refresh_token
        )

        mock_set_auth_cookies.assert_called_once_with(
            response,
            access_token,
            refresh_token,
        )
        self.assertEqual(result, response)

    @patch('hasta_la_vista_money.users.services.auth.set_auth_cookies')
    def test_set_auth_cookies_in_response_without_refresh_token(
        self,
        mock_set_auth_cookies,
    ) -> None:
        response = HttpResponse()
        access_token = 'test_access_token'

        mock_set_auth_cookies.return_value = response

        result = set_auth_cookies_in_response(response, access_token)

        mock_set_auth_cookies.assert_called_once_with(
            response,
            access_token,
            None,
        )
        self.assertEqual(result, response)

    @patch('hasta_la_vista_money.users.services.auth.set_auth_cookies')
    def test_set_auth_cookies_in_response_with_none_refresh_token(
        self,
        mock_set_auth_cookies,
    ) -> None:
        response = HttpResponse()
        access_token = 'test_access_token'
        refresh_token = None

        mock_set_auth_cookies.return_value = response

        result = set_auth_cookies_in_response(
            response, access_token, refresh_token
        )

        mock_set_auth_cookies.assert_called_once_with(
            response,
            access_token,
            None,
        )
        self.assertEqual(result, response)
