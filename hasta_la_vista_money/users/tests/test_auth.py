from collections.abc import Sequence
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase

from hasta_la_vista_money.users.services.auth import (
    LoginResult,
    login_user,
    set_auth_cookies_in_response,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


def _dummy_get_response(_request: HttpRequest) -> HttpResponse:
    return HttpResponse()


class LoginUserServiceTest(TestCase):
    """Tests for login_user service function."""

    fixtures: Sequence[str] = ['users.yaml']

    def setUp(self) -> None:
        self.factory: RequestFactory = RequestFactory()
        user = User.objects.first()
        if user is None:
            error_msg: str = 'No user found in fixtures'
            raise ValueError(error_msg)
        self.user: UserType = user
        self.user.set_password('testpassword')
        self.user.save()

    def get_request(self) -> HttpRequest:
        request: HttpRequest = self.factory.post('/login/')
        SessionMiddleware(_dummy_get_response).process_request(request)
        request.session.save()
        MessageMiddleware(_dummy_get_response).process_request(request)
        return request

    def test_login_user_success(self) -> None:
        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result: LoginResult = login_user(request, form, 'Success!')
        self.assertTrue(result['success'])
        self.assertIn('access', result)
        self.assertIn('refresh', result)
        self.assertEqual(result['user'], self.user)

    def test_login_user_failure(self) -> None:
        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'wrongpassword',
            },
        )
        form.is_valid()
        result: LoginResult = login_user(request, form, 'Fail!')
        self.assertFalse(result['success'])

    def test_login_user_nonexistent_user(self) -> None:
        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={
                'username': 'nonexistent_user',
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result: LoginResult = login_user(request, form, 'Fail!')
        self.assertFalse(result['success'])

    def test_login_user_inactive_user(self) -> None:
        self.user.is_active = False
        self.user.save()

        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result: LoginResult = login_user(request, form, 'Fail!')
        self.assertFalse(result['success'])

    @patch('hasta_la_vista_money.users.services.auth.RefreshToken')
    def test_login_user_jwt_token_generation_success(
        self,
        mock_refresh_token: MagicMock,
    ) -> None:
        mock_token_instance: MagicMock = MagicMock()
        mock_token_instance.access_token = 'mock_access_token'
        mock_str: MagicMock = MagicMock(return_value='mock_refresh_token')
        mock_token_instance.__str__ = mock_str  # type: ignore[method-assign]
        mock_refresh_token.for_user.return_value = mock_token_instance

        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result: LoginResult = login_user(request, form, 'Success!')

        self.assertTrue(result['success'])
        self.assertEqual(result['access'], 'mock_access_token')
        self.assertEqual(result['refresh'], 'mock_refresh_token')

    @patch('hasta_la_vista_money.users.services.auth.RefreshToken')
    def test_login_user_jwt_token_generation_failure(
        self,
        mock_refresh_token: MagicMock,
    ) -> None:
        mock_refresh_token.for_user.side_effect = ValueError(
            'Token generation failed',
        )

        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result: LoginResult = login_user(request, form, 'Success!')

        self.assertTrue(result['success'])
        self.assertIsNone(result['access'])
        self.assertIsNone(result['refresh'])

    @patch('hasta_la_vista_money.users.services.auth.RefreshToken')
    def test_login_user_jwt_token_type_error(
        self,
        mock_refresh_token: MagicMock,
    ) -> None:
        mock_refresh_token.for_user.side_effect = TypeError('Type error')

        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result: LoginResult = login_user(request, form, 'Success!')

        self.assertTrue(result['success'])
        self.assertIsNone(result['access'])
        self.assertIsNone(result['refresh'])

    @patch('hasta_la_vista_money.users.services.auth.RefreshToken')
    def test_login_user_jwt_token_attribute_error(
        self,
        mock_refresh_token: MagicMock,
    ) -> None:
        mock_refresh_token.for_user.side_effect = AttributeError(
            'Attribute error',
        )

        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={
                'username': str(self.user.get_username()),
                'password': 'testpassword',
            },
        )
        form.is_valid()
        result: LoginResult = login_user(request, form, 'Success!')

        self.assertTrue(result['success'])
        self.assertIsNone(result['access'])
        self.assertIsNone(result['refresh'])

    def test_login_user_empty_form_data(self) -> None:
        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(request, data={})
        form.is_valid()

        with self.assertRaises(KeyError):
            login_user(request, form, 'Fail!')

    def test_login_user_missing_username(self) -> None:
        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={'password': 'testpassword'},
        )
        form.is_valid()

        with self.assertRaises(KeyError):
            login_user(request, form, 'Fail!')

    def test_login_user_missing_password(self) -> None:
        request: HttpRequest = self.get_request()
        form: AuthenticationForm = AuthenticationForm(
            request,
            data={'username': str(self.user.get_username())},
        )
        form.is_valid()

        with self.assertRaises(KeyError):
            login_user(request, form, 'Fail!')


class SetAuthCookiesInResponseTest(TestCase):
    """Tests for set_auth_cookies_in_response helper function."""

    def setUp(self) -> None:
        self.factory: RequestFactory = RequestFactory()

    @patch('hasta_la_vista_money.users.services.auth.set_auth_cookies')
    def test_set_auth_cookies_in_response_with_refresh_token(
        self,
        mock_set_auth_cookies: MagicMock,
    ) -> None:
        response: HttpResponse = HttpResponse()
        access_token: str = 'test_access_token'
        refresh_token: str = 'test_refresh_token'

        mock_set_auth_cookies.return_value = response

        result: HttpResponse = set_auth_cookies_in_response(
            response,
            access_token,
            refresh_token,
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
        mock_set_auth_cookies: MagicMock,
    ) -> None:
        response: HttpResponse = HttpResponse()
        access_token: str = 'test_access_token'

        mock_set_auth_cookies.return_value = response

        result: HttpResponse = set_auth_cookies_in_response(
            response,
            access_token,
        )

        mock_set_auth_cookies.assert_called_once_with(
            response,
            access_token,
            None,
        )
        self.assertEqual(result, response)

    @patch('hasta_la_vista_money.users.services.auth.set_auth_cookies')
    def test_set_auth_cookies_in_response_with_none_refresh_token(
        self,
        mock_set_auth_cookies: MagicMock,
    ) -> None:
        response: HttpResponse = HttpResponse()
        access_token: str = 'test_access_token'
        refresh_token: str | None = None

        mock_set_auth_cookies.return_value = response

        result: HttpResponse = set_auth_cookies_in_response(
            response,
            access_token,
            refresh_token,
        )

        mock_set_auth_cookies.assert_called_once_with(
            response,
            access_token,
            None,
        )
        self.assertEqual(result, response)
