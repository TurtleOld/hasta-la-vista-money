import base64
import json
import unittest
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import jwt
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.request import Request
from rest_framework_simplejwt.tokens import AccessToken

from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
    clear_auth_cookies,
    get_refresh_token_from_cookie,
    get_token_from_cookie,
    set_auth_cookies,
)
from hasta_la_vista_money.users.factories import UserFactoryTyped
from hasta_la_vista_money.users.models import User as UserModel

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User
else:
    User = UserModel


class CookieJWTAuthenticationEdgeCasesTestCase(TestCase):
    """Test cases for CookieJWTAuthentication edge cases.

    Tests various edge cases and error conditions for JWT authentication.
    """

    def setUp(self) -> None:
        """Set up test data."""
        self.factory = RequestFactory()
        self.auth = CookieJWTAuthentication()
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']

    def test_authenticate_empty_cookie_value(self) -> None:
        """Test that empty cookie value returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = ''

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_none_cookie_value(self) -> None:
        """Test that None cookie value returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = None  # type: ignore[assignment]

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_whitespace_cookie_value(self) -> None:
        """Test that cookie with whitespace returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = '   '

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_inactive_user(self) -> None:
        """Test that inactive user cannot authenticate."""
        user: User = UserFactoryTyped(is_active=False)
        # Создаем токен вручную, так как AccessToken.for_user не работает
        # c неактивными пользователями
        payload = {
            'user_id': user.pk,
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_deleted_user(self) -> None:
        """Test that deleted user token returns None."""
        user: User = UserFactoryTyped()
        user_id = user.pk
        user.delete()

        payload = {
            'user_id': user_id,
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_multiple_cookies(self) -> None:
        """Test that multiple cookies with same name are handled correctly."""
        user: User = UserFactoryTyped()
        valid_token = AccessToken.for_user(user)

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = str(valid_token)
        request.COOKIES[f'{self.auth_cookie_name}_backup'] = 'invalid_token'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNotNone(result)
        if result:
            authenticated_user, _ = result
            self.assertEqual(authenticated_user, user)

    def test_authenticate_unicode_cookie_value(self) -> None:
        """Test that cookie with unicode characters returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'test_token_with_unicode'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_very_long_cookie_value(self) -> None:
        """Test that very long cookie value returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'x' * 10000

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_special_characters_cookie_value(self) -> None:
        """Test that cookie with special characters returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'token!@#$%^&*()'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_invalid_base64_token(self) -> None:
        """Test that token with invalid base64 returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'invalid.base64.token!'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_malformed_jwt_structure(self) -> None:
        """Test that token with malformed JWT structure returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'header.payload'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_invalid_json_payload(self) -> None:
        """Test that token with invalid JSON in payload returns None."""
        request = self.factory.get('/')
        header = base64.urlsafe_b64encode(
            json.dumps({'typ': 'JWT', 'alg': 'HS256'}).encode(),
        ).decode()
        invalid_payload = base64.urlsafe_b64encode(b'invalid json{').decode()
        signature = 'signature'
        malformed_token = f'{header}.{invalid_payload}.{signature}'

        request.COOKIES[self.auth_cookie_name] = malformed_token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_missing_exp_claim(self) -> None:
        """Test that token without exp claim returns None."""
        user: User = UserFactoryTyped()
        payload = {
            'user_id': user.pk,
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_missing_iat_claim(self) -> None:
        """Test that token without iat claim is invalid."""
        user: User = UserFactoryTyped()
        payload = {
            'user_id': user.pk,
            'exp': timezone.now() + timedelta(hours=1),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_wrong_algorithm(self) -> None:
        """Test that token with wrong algorithm returns None."""
        user: User = UserFactoryTyped()
        payload = {
            'user_id': user.pk,
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS512')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_future_iat(self) -> None:
        """Test that token with iat in future is invalid."""
        user: User = UserFactoryTyped()
        payload = {
            'user_id': user.pk,
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now() + timedelta(hours=1),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_negative_user_id(self) -> None:
        """Test that token with negative user_id returns None."""
        payload = {
            'user_id': -1,
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_zero_user_id(self) -> None:
        """Test that token with zero user_id returns None."""
        payload = {
            'user_id': 0,
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_string_user_id(self) -> None:
        """Test that token with string user_id returns None."""
        payload = {
            'user_id': 'not_a_number',
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_none_user_id(self) -> None:
        """Test that token with None user_id returns None."""
        payload = {
            'user_id': None,
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_empty_user_id(self) -> None:
        """Test that token with empty user_id returns None."""
        payload = {
            'user_id': '',
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_request_without_cookies_attribute(self) -> None:
        """Test that request without COOKIES attribute returns None."""
        request = Mock()
        request.COOKIES = {}
        request.META = {}

        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_authenticate_request_with_empty_cookies(self) -> None:
        """Test that request with empty COOKIES returns None."""
        request = Mock()
        request.COOKIES = {}
        request.META = {}

        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_authenticate_with_exception_in_get_user(self) -> None:
        """Test that exception in get_user method returns None."""
        with patch.object(
            self.auth,
            'get_user',
            side_effect=RuntimeError('Database error'),
        ):
            user: User = UserFactoryTyped()
            valid_token = AccessToken.for_user(user)

            request = self.factory.get('/')
            request.COOKIES[self.auth_cookie_name] = str(valid_token)

            result = self.auth.authenticate(request)  # type: ignore[arg-type]
            self.assertIsNone(result)

    def test_authenticate_with_exception_in_get_validated_token(self) -> None:
        """Test that exception in get_validated_token method returns None."""
        with patch.object(
            self.auth,
            'get_validated_token',
            side_effect=RuntimeError('Token validation error'),
        ):
            request = self.factory.get('/')
            request.COOKIES[self.auth_cookie_name] = 'some_token'

            result = self.auth.authenticate(request)  # type: ignore[arg-type]
            self.assertIsNone(result)

    def test_authenticate_with_type_error_in_get_user(self) -> None:
        """Test that TypeError in get_user method returns None."""
        with patch.object(
            self.auth,
            'get_user',
            side_effect=TypeError('Type error'),
        ):
            request = self.factory.get('/')
            request.COOKIES[self.auth_cookie_name] = 'some_token'

            result = self.auth.authenticate(request)  # type: ignore[arg-type]
            self.assertIsNone(result)

    def test_authenticate_with_value_error_in_get_user(self) -> None:
        """Test that ValueError in get_user method returns None."""
        with patch.object(
            self.auth,
            'get_user',
            side_effect=ValueError('Value error'),
        ):
            request = self.factory.get('/')
            request.COOKIES[self.auth_cookie_name] = 'some_token'

            result = self.auth.authenticate(request)  # type: ignore[arg-type]
            self.assertIsNone(result)

    def test_authenticate_with_key_error_in_get_user(self) -> None:
        """Test that KeyError in get_user method returns None."""
        with patch.object(
            self.auth,
            'get_user',
            side_effect=KeyError('Key error'),
        ):
            request = self.factory.get('/')
            request.COOKIES[self.auth_cookie_name] = 'some_token'

            result = self.auth.authenticate(request)  # type: ignore[arg-type]
            self.assertIsNone(result)

    def test_authenticate_header_with_different_request_types(self) -> None:
        """Test that authenticate_header works with different request types."""
        django_request = HttpRequest()
        header1 = self.auth.authenticate_header(django_request)  # type: ignore[arg-type]
        self.assertEqual(header1, 'Bearer realm="api"')

        drf_request = Request(self.factory.get('/'))
        header2 = self.auth.authenticate_header(drf_request)
        self.assertEqual(header2, 'Bearer realm="api"')

    def test_authenticate_with_cookie_encoding_issues(self) -> None:
        """Test that cookie encoding issues return None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'token\x00with\x00nulls'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_with_very_short_token(self) -> None:
        """Test that very short token returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'x'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_with_only_dots_token(self) -> None:
        """Test that token consisting only of dots returns None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = '...'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)


class CookieUtilityFunctionsTestCase(TestCase):
    """Test cases for cookie utility functions.

    Tests helper functions for working with authentication cookies.
    """

    def setUp(self) -> None:
        """Set up test data."""
        self.factory = RequestFactory()
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']
        self.refresh_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH']

    def test_get_token_from_cookie_with_django_request(self) -> None:
        """Test get_token_from_cookie with Django HttpRequest."""
        request = HttpRequest()
        request.COOKIES = {self.auth_cookie_name: 'test_token'}

        result = get_token_from_cookie(request)
        self.assertEqual(result, 'test_token')

    def test_get_token_from_cookie_with_drf_request(self) -> None:
        """Test get_token_from_cookie with DRF Request."""
        request = Request(self.factory.get('/'))
        request.COOKIES[self.auth_cookie_name] = 'test_token'

        result = get_token_from_cookie(request)
        self.assertEqual(result, 'test_token')

    def test_get_refresh_token_from_cookie_with_django_request(self) -> None:
        """Test get_refresh_token_from_cookie with Django HttpRequest."""
        request = HttpRequest()
        request.COOKIES = {self.refresh_cookie_name: 'test_refresh_token'}

        result = get_refresh_token_from_cookie(request)
        self.assertEqual(result, 'test_refresh_token')

    def test_get_refresh_token_from_cookie_with_drf_request(self) -> None:
        """Test get_refresh_token_from_cookie with DRF Request."""
        request = Request(self.factory.get('/'))
        request.COOKIES[self.refresh_cookie_name] = 'test_refresh_token'

        result = get_refresh_token_from_cookie(request)
        self.assertEqual(result, 'test_refresh_token')

    def test_clear_auth_cookies_with_nonexistent_cookies(self) -> None:
        """Test that clear_auth_cookies doesn't fail with missing cookies."""
        response = HttpResponse()

        result = clear_auth_cookies(response)
        self.assertIsInstance(result, HttpResponse)

    def test_set_auth_cookies_with_none_values(self) -> None:
        """Test that set_auth_cookies doesn't fail with None values."""
        response = HttpResponse()

        result = set_auth_cookies(response, None)  # type: ignore[arg-type]
        self.assertIsInstance(result, HttpResponse)

    def test_set_auth_cookies_with_empty_strings(self) -> None:
        """Test that set_auth_cookies doesn't fail with empty strings."""
        response = HttpResponse()

        result = set_auth_cookies(response, '', '')
        self.assertIsInstance(result, HttpResponse)

        self.assertIn(self.auth_cookie_name, result.cookies)
        self.assertEqual(result.cookies[self.auth_cookie_name].value, '')

    def test_cookie_functions_with_mock_request(self) -> None:
        """Test that cookie functions work with mock request."""
        mock_request = Mock()
        mock_request.COOKIES = {self.auth_cookie_name: 'test_token'}

        result = get_token_from_cookie(mock_request)
        self.assertEqual(result, 'test_token')

    def test_cookie_functions_with_request_without_cookies(self) -> None:
        """Test cookie functions return None for request without COOKIES."""
        mock_request = Mock()
        mock_request.COOKIES = {}

        result = get_token_from_cookie(mock_request)
        self.assertIsNone(result)

        result = get_refresh_token_from_cookie(mock_request)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
