import unittest
from datetime import timedelta
from unittest.mock import patch

import jwt
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
    clear_auth_cookies,
    get_refresh_token_from_cookie,
    get_token_from_cookie,
    set_auth_cookies,
)
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.models import User


class CookieJWTAuthenticationTestCase(TestCase):
    """Тесты для класса CookieJWTAuthentication."""

    def setUp(self) -> None:
        """Настройка тестовых данных."""
        self.factory = RequestFactory()
        self.auth = CookieJWTAuthentication()
        self.user: User = UserFactory()  # type: ignore[assignment,no-untyped-call]
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']
        self.refresh_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH']

    def _create_valid_token(self, user: User) -> str:
        """Создает валидный JWT токен для пользователя."""
        token = AccessToken.for_user(user)
        return str(token)

    def _create_expired_token(self, user: User) -> str:
        """Создает истекший JWT токен."""
        now = timezone.now()
        payload = {
            'user_id': user.pk,
            'exp': now - timedelta(hours=1),
            'iat': now - timedelta(hours=2),
            'token_type': 'access',
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

    def _create_invalid_signature_token(self, user: User) -> str:
        """Создает токен с неверной подписью."""
        payload = {
            'user_id': user.pk,
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        return jwt.encode(payload, 'wrong_secret', algorithm='HS256')

    def _create_token_without_user_id(self) -> str:
        """Создает токен без user_id в payload."""
        payload = {
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

    def _create_malformed_token(self) -> str:
        """Создает некорректно сформированный токен."""
        return 'invalid.base64.token'

    def test_authenticate_no_cookie(self) -> None:
        """Отсутствие куки jwt возвращает None."""
        request = self.factory.get('/')
        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_no_authorization_header(self) -> None:
        """При отсутствии Authorization используется кука."""
        valid_token = self._create_valid_token(self.user)
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = valid_token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNotNone(result)
        if result:
            user, token = result
            self.assertEqual(user, self.user)
            self.assertIsNotNone(token)

    def test_authenticate_invalid_signature(self) -> None:
        """Неверная подпись токена возвращает None."""
        invalid_token = self._create_invalid_signature_token(self.user)
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = invalid_token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_expired_token(self) -> None:
        """Истекший токен возвращает None."""
        expired_token = self._create_expired_token(self.user)
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = expired_token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_valid_token(self) -> None:
        """Валидный токен возвращает пару (user, token)."""
        valid_token = self._create_valid_token(self.user)
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = valid_token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNotNone(result)
        if result:
            user, token = result
            self.assertEqual(user, self.user)
            self.assertIsNotNone(token)

    def test_authenticate_token_without_user_id(self) -> None:
        """Токен без user_id в payload возвращает None."""
        token_without_user_id = self._create_token_without_user_id()
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token_without_user_id

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_nonexistent_user(self) -> None:
        """Несуществующий user_id возвращает None."""
        payload = {
            'user_id': 99999,
            'exp': timezone.now() + timedelta(hours=1),
            'iat': timezone.now(),
            'token_type': 'access',
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_malformed_token(self) -> None:
        """Некорректный формат токена (не base64) возвращает None."""
        malformed_token = self._create_malformed_token()
        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = malformed_token

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNone(result)

    def test_authenticate_authorization_header_ignored_with_cookie(
        self,
    ) -> None:
        """Заголовок Authorization игнорируется при наличии куки."""
        valid_token = self._create_valid_token(self.user)
        invalid_token = 'invalid.token.here'

        request = self.factory.get('/')
        request.COOKIES[self.auth_cookie_name] = valid_token
        request.META['HTTP_AUTHORIZATION'] = f'Bearer {invalid_token}'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNotNone(result)
        if result:
            user, _ = result
            self.assertEqual(user, self.user)

    def test_authenticate_header_only(self) -> None:
        """Используется только Authorization если нет куки."""
        valid_token = self._create_valid_token(self.user)

        request = self.factory.get('/')
        request.META['HTTP_AUTHORIZATION'] = f'Bearer {valid_token}'

        result = self.auth.authenticate(request)  # type: ignore[arg-type]
        self.assertIsNotNone(result)
        if result:
            user, _ = result
            self.assertEqual(user, self.user)

    def test_authenticate_header(self) -> None:
        """Метод authenticate_header возвращает корректное значение."""
        request = self.factory.get('/')
        header = self.auth.authenticate_header(request)  # type: ignore[arg-type]
        self.assertEqual(header, 'Bearer realm="api"')

    def test_raise_invalid_user_type(self) -> None:
        """Выбрасывается исключение при неправильном типе пользователя."""
        with (
            patch.object(self.auth, 'get_user', return_value='not_a_user'),
            patch.object(
                self.auth,
                'get_validated_token',
                return_value='token',
            ),
        ):
            request = self.factory.get('/')
            request.COOKIES[self.auth_cookie_name] = 'some_token'

            with self.assertRaises(TypeError) as context:
                self.auth.authenticate(request)  # type: ignore[arg-type]

            self.assertIn('Ожидался экземпляр User', str(context.exception))


class CookieSecurityTestCase(TestCase):
    """Тесты безопасности кук."""

    def setUp(self) -> None:
        """Настройка тестовых данных."""
        self.user: User = UserFactory()  # type: ignore[assignment,no-untyped-call]
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']
        self.refresh_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH']

    def test_set_auth_cookies_security_attributes(self) -> None:
        """Куки устанавливаются с правильными атрибутами безопасности."""
        response = HttpResponse()
        access_token = 'test_access_token'
        refresh_token = 'test_refresh_token'

        result = set_auth_cookies(response, access_token, refresh_token)

        self.assertIn(self.auth_cookie_name, result.cookies)
        self.assertIn(self.refresh_cookie_name, result.cookies)

        access_cookie = result.cookies[self.auth_cookie_name]
        self.assertTrue(access_cookie['httponly'])
        self.assertEqual(
            bool(access_cookie['secure']),
            settings.SIMPLE_JWT['AUTH_COOKIE_SECURE'],
        )
        self.assertEqual(
            access_cookie['samesite'],
            settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE'],
        )

        refresh_cookie = result.cookies[self.refresh_cookie_name]
        self.assertTrue(refresh_cookie['httponly'])
        self.assertEqual(
            bool(refresh_cookie['secure']),
            settings.SIMPLE_JWT['AUTH_COOKIE_SECURE'],
        )
        self.assertEqual(
            refresh_cookie['samesite'],
            settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE'],
        )

    def test_set_auth_cookies_no_refresh_token(self) -> None:
        """Установка только access token без refresh token."""
        response = HttpResponse()
        access_token = 'test_access_token'

        result = set_auth_cookies(response, access_token)

        self.assertIn(self.auth_cookie_name, result.cookies)
        self.assertNotIn(self.refresh_cookie_name, result.cookies)

    def test_clear_auth_cookies(self) -> None:
        """Очистка кук аутентификации работает корректно."""
        response = HttpResponse()

        set_auth_cookies(response, 'access', 'refresh')
        self.assertIn(self.auth_cookie_name, response.cookies)
        self.assertIn(self.refresh_cookie_name, response.cookies)

        result = clear_auth_cookies(response)

        access_cookie = result.cookies[self.auth_cookie_name]
        refresh_cookie = result.cookies[self.refresh_cookie_name]

        self.assertEqual(access_cookie.value, '')
        self.assertEqual(refresh_cookie.value, '')

    def test_get_token_from_cookie(self) -> None:
        """Получение токена из куки работает корректно."""
        factory = RequestFactory()
        request = factory.get('/')
        token = 'test_token'
        request.COOKIES[self.auth_cookie_name] = token

        result = get_token_from_cookie(request)
        self.assertEqual(result, token)

    def test_get_token_from_cookie_none(self) -> None:
        """Получение токена из куки возвращает None когда кука отсутствует."""
        factory = RequestFactory()
        request = factory.get('/')

        result = get_token_from_cookie(request)
        self.assertIsNone(result)

    def test_get_refresh_token_from_cookie(self) -> None:
        """Получение refresh токена из куки работает корректно."""
        factory = RequestFactory()
        request = factory.get('/')
        token = 'test_refresh_token'
        request.COOKIES[self.refresh_cookie_name] = token

        result = get_refresh_token_from_cookie(request)
        self.assertEqual(result, token)

    def test_get_refresh_token_from_cookie_none(self) -> None:
        """Получение refresh токена возвращает None если кука отсутствует."""
        factory = RequestFactory()
        request = factory.get('/')

        result = get_refresh_token_from_cookie(request)
        self.assertIsNone(result)


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
        request.COOKIES[self.auth_cookie_name] = ''

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
        user: User = UserFactory(is_active=False)  # type: ignore[assignment,no-untyped-call]
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
        user: User = UserFactory()  # type: ignore[assignment,no-untyped-call]
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
        user: User = UserFactory()  # type: ignore[assignment,no-untyped-call]
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


if __name__ == '__main__':
    unittest.main()
