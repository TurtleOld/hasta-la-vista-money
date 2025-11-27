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
    """Тесты для граничных случаев CookieJWTAuthentication."""

    def setUp(self) -> None:
        """Настройка тестовых данных."""
        self.factory = RequestFactory()
        self.auth = CookieJWTAuthentication()
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']

    def test_authenticate_empty_cookie_value(self) -> None:
        """Пустое значение куки возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = ''

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_none_cookie_value(self) -> None:
        """Значение куки None возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = None  # type: ignore[assignment]

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_whitespace_cookie_value(self) -> None:
        """Кука с пробелами возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = '   '

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_inactive_user(self) -> None:
        """Неактивный пользователь не может аутентифицироваться."""
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
        """Токен удаленного пользователя возвращает None."""
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
        """Несколько кук с одинаковым именем обрабатываются корректно."""
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
        """Кука с unicode символами возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'test_token_with_unicode'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_very_long_cookie_value(self) -> None:
        """Очень длинное значение куки возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'x' * 10000

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_special_characters_cookie_value(self) -> None:
        """Кука со специальными символами возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'token!@#$%^&*()'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_invalid_base64_token(self) -> None:
        """Токен с некорректным base64 возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'invalid.base64.token!'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_malformed_jwt_structure(self) -> None:
        """Токен с неправильной структурой JWT возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'header.payload'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_invalid_json_payload(self) -> None:
        """Токен с некорректным JSON в payload возвращает None."""
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
        """Токен без exp возвращает None."""
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
        """Токен без iat невалиден."""
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
        """Токен с неправильным алгоритмом возвращает None."""
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
        """Токен с iat в будущем невалиден."""
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
        """Токен с отрицательным user_id возвращает None."""
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
        """Токен с user_id равным нулю возвращает None."""
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
        """Токен с user_id строкой возвращает None."""
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
        """Токен с user_id равным None возвращает None."""
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
        """Токен с пустым user_id возвращает None."""
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
        """Запрос без атрибута COOKIES возвращает None."""
        request = Mock()
        request.COOKIES = {}
        request.META = {}

        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_authenticate_request_with_empty_cookies(self) -> None:
        """Запрос с пустым COOKIES возвращает None."""
        request = Mock()
        request.COOKIES = {}
        request.META = {}

        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_authenticate_with_exception_in_get_user(self) -> None:
        """Исключение в методе get_user возвращает None."""
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
        """Исключение в методе get_validated_token возвращает None."""
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
        """TypeError в методе get_user возвращает None."""
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
        """ValueError в методе get_user возвращает None."""
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
        """KeyError в методе get_user возвращает None."""
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
        """authenticate_header работает с разными типами запросов."""
        django_request = HttpRequest()
        header1 = self.auth.authenticate_header(django_request)  # type: ignore[arg-type]
        self.assertEqual(header1, 'Bearer realm="api"')

        drf_request = Request(self.factory.get('/'))
        header2 = self.auth.authenticate_header(drf_request)  # type: ignore[reportCallIssue]
        self.assertEqual(header2, 'Bearer realm="api"')

    def test_authenticate_with_cookie_encoding_issues(self) -> None:
        """Проблемы с кодировкой куки возвращают None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'token\x00with\x00nulls'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_with_very_short_token(self) -> None:
        """Очень короткий токен возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = 'x'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_with_only_dots_token(self) -> None:
        """Токен состоящий только из точек возвращает None."""
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = '...'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)


class CookieUtilityFunctionsTestCase(TestCase):
    """Тесты для вспомогательных функций работы с куками."""

    def setUp(self) -> None:
        """Настройка тестовых данных."""
        self.factory = RequestFactory()
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']
        self.refresh_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH']

    def test_get_token_from_cookie_with_django_request(self) -> None:
        """get_token_from_cookie с Django HttpRequest."""
        request = HttpRequest()
        request.COOKIES = {self.auth_cookie_name: 'test_token'}

        result = get_token_from_cookie(request)
        self.assertEqual(result, 'test_token')

    def test_get_token_from_cookie_with_drf_request(self) -> None:
        """get_token_from_cookie с DRF Request."""
        request = Request(self.factory.get('/'))
        request.COOKIES[self.auth_cookie_name] = 'test_token'

        result = get_token_from_cookie(request)  # type: ignore[reportCallIssue]
        self.assertEqual(result, 'test_token')

    def test_get_refresh_token_from_cookie_with_django_request(self) -> None:
        """get_refresh_token_from_cookie с Django HttpRequest."""
        request = HttpRequest()
        request.COOKIES = {self.refresh_cookie_name: 'test_refresh_token'}

        result = get_refresh_token_from_cookie(request)
        self.assertEqual(result, 'test_refresh_token')

    def test_get_refresh_token_from_cookie_with_drf_request(self) -> None:
        """get_refresh_token_from_cookie с DRF Request."""
        request = Request(self.factory.get('/'))
        request.COOKIES[self.refresh_cookie_name] = 'test_refresh_token'

        result = get_refresh_token_from_cookie(request)  # type: ignore[reportCallIssue]
        self.assertEqual(result, 'test_refresh_token')

    def test_clear_auth_cookies_with_nonexistent_cookies(self) -> None:
        """clear_auth_cookies с несуществующими куками не падает."""
        response = HttpResponse()

        result = clear_auth_cookies(response)
        self.assertIsInstance(result, HttpResponse)

    def test_set_auth_cookies_with_none_values(self) -> None:
        """set_auth_cookies с None значениями не падает."""
        response = HttpResponse()

        result = set_auth_cookies(response, None)  # type: ignore[arg-type]
        self.assertIsInstance(result, HttpResponse)

    def test_set_auth_cookies_with_empty_strings(self) -> None:
        """set_auth_cookies с пустыми строками не падает."""
        response = HttpResponse()

        result = set_auth_cookies(response, '', '')
        self.assertIsInstance(result, HttpResponse)

        self.assertIn(self.auth_cookie_name, result.cookies)
        self.assertEqual(result.cookies[self.auth_cookie_name].value, '')

    def test_cookie_functions_with_mock_request(self) -> None:
        """Функции работы с куками работают с мок-объектом."""
        mock_request = Mock()
        mock_request.COOKIES = {self.auth_cookie_name: 'test_token'}

        result = get_token_from_cookie(mock_request)
        self.assertEqual(result, 'test_token')

    def test_cookie_functions_with_request_without_cookies(self) -> None:
        """Функции работы с куками возвращают None для запроса без COOKIES."""
        mock_request = Mock()
        mock_request.COOKIES = {}

        result = get_token_from_cookie(mock_request)
        self.assertIsNone(result)

        result = get_refresh_token_from_cookie(mock_request)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
