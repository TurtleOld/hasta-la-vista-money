import unittest

from django.conf import settings
from django.http import HttpResponse
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from hasta_la_vista_money.authentication.authentication import set_auth_cookies
from hasta_la_vista_money.users.factories import UserFactory


class XSSProtectionTestCase(TestCase):
    """Тесты защиты от XSS атак."""

    def setUp(self) -> None:
        """Настройка тестовых данных."""
        self.user = UserFactory()
        self.factory = APIRequestFactory()
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']

    def test_token_not_in_response_body(self) -> None:
        """Токен не присутствует в теле ответа."""
        response = HttpResponse()
        access_token = 'sensitive_access_token_12345'
        refresh_token = 'sensitive_refresh_token_67890'

        result = set_auth_cookies(response, access_token, refresh_token)

        response_content = result.content.decode('utf-8')
        self.assertNotIn(access_token, response_content)
        self.assertNotIn(refresh_token, response_content)

        self.assertIn(self.auth_cookie_name, result.cookies)
        self.assertEqual(
            result.cookies[self.auth_cookie_name].value,
            access_token,
        )

    def test_token_only_in_cookies(self) -> None:
        """Токен передается только в куках, не в заголовках."""
        response = HttpResponse()
        access_token = 'test_access_token'

        result = set_auth_cookies(response, access_token)

        self.assertNotIn('Authorization', result)
        self.assertNotIn('X-Auth-Token', result)

        self.assertIn(self.auth_cookie_name, result.cookies)
        self.assertEqual(
            result.cookies[self.auth_cookie_name].value,
            access_token,
        )

    def test_cookie_httponly_attribute(self) -> None:
        """Кука имеет атрибут HttpOnly=True."""
        response = HttpResponse()
        access_token = 'test_token'

        result = set_auth_cookies(response, access_token)

        cookie = result.cookies[self.auth_cookie_name]
        self.assertTrue(cookie['httponly'])

        cookie_str = str(cookie)
        self.assertIn('HttpOnly', cookie_str)

    def test_cookie_secure_attribute(self) -> None:
        """Кука имеет атрибут Secure в соответствии с настройками."""
        response = HttpResponse()
        access_token = 'test_token'

        result = set_auth_cookies(response, access_token)

        cookie = result.cookies[self.auth_cookie_name]
        expected_secure = settings.SIMPLE_JWT['AUTH_COOKIE_SECURE']
        self.assertEqual(bool(cookie['secure']), expected_secure)

    def test_cookie_samesite_attribute(self) -> None:
        """Кука имеет атрибут SameSite."""
        response = HttpResponse()
        access_token = 'test_token'

        result = set_auth_cookies(response, access_token)

        cookie = result.cookies[self.auth_cookie_name]
        expected_samesite = settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE']
        self.assertEqual(cookie['samesite'], expected_samesite)

        cookie_str = str(cookie)
        self.assertIn(f'SameSite={expected_samesite}', cookie_str)

    def test_cookie_path_attribute(self) -> None:
        """Кука имеет корректный путь."""
        response = HttpResponse()
        access_token = 'test_token'

        result = set_auth_cookies(response, access_token)

        cookie = result.cookies[self.auth_cookie_name]
        expected_path = settings.SIMPLE_JWT['AUTH_COOKIE_PATH']
        self.assertEqual(cookie['path'], expected_path)

    def test_cookie_domain_attribute(self) -> None:
        """Кука имеет корректный домен."""
        response = HttpResponse()
        access_token = 'test_token'

        result = set_auth_cookies(response, access_token)

        cookie = result.cookies[self.auth_cookie_name]
        expected_domain = settings.SIMPLE_JWT['AUTH_COOKIE_DOMAIN']
        if expected_domain is None:
            # Django возвращает строку 'None' вместо None
            self.assertIn(cookie['domain'], [None, 'None'])
        else:
            self.assertEqual(cookie['domain'], expected_domain)

    def test_cookie_max_age_attribute(self) -> None:
        """Кука имеет корректное время жизни."""
        response = HttpResponse()
        access_token = 'test_token'

        result = set_auth_cookies(response, access_token)

        cookie = result.cookies[self.auth_cookie_name]
        expected_max_age = settings.SIMPLE_JWT['AUTH_COOKIE_MAX_AGE']
        self.assertEqual(cookie['max-age'], expected_max_age)

    def test_multiple_cookies_security(self) -> None:
        """Все куки имеют корректные атрибуты безопасности."""
        response = HttpResponse()
        access_token = 'access_token'
        refresh_token = 'refresh_token'

        result = set_auth_cookies(response, access_token, refresh_token)

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

        refresh_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH']
        refresh_cookie = result.cookies[refresh_cookie_name]
        self.assertTrue(refresh_cookie['httponly'])
        self.assertEqual(
            bool(refresh_cookie['secure']),
            settings.SIMPLE_JWT['AUTH_COOKIE_SECURE'],
        )
        self.assertEqual(
            refresh_cookie['samesite'],
            settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE'],
        )

    def test_cookie_value_encoding(self) -> None:
        """Значение куки корректно кодируется."""
        response = HttpResponse()
        access_token = (
            'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9'
            '.eyJ1c2VyX2lkIjoxLCJleHAiOjE2MzQ1Njc4OTB9.signature'
        )

        result = set_auth_cookies(response, access_token)

        cookie = result.cookies[self.auth_cookie_name]
        self.assertEqual(cookie.value, access_token)

        self.assertIsInstance(cookie.value, str)

    def test_cookie_overwrite_protection(self) -> None:
        """Защита от перезаписи кук работает корректно."""
        response = HttpResponse()
        access_token1 = 'first_token'
        access_token2 = 'second_token'

        result1 = set_auth_cookies(response, access_token1)
        self.assertEqual(
            result1.cookies[self.auth_cookie_name].value,
            access_token1,
        )

        result2 = set_auth_cookies(response, access_token2)
        self.assertEqual(
            result2.cookies[self.auth_cookie_name].value,
            access_token2,
        )

        response_content = result2.content.decode('utf-8')
        self.assertNotIn(access_token1, response_content)
        self.assertNotIn(access_token2, response_content)


class SecurityHeadersTestCase(TestCase):
    """Тесты безопасности заголовков."""

    def setUp(self) -> None:
        """Настройка тестовых данных."""
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']

    def test_no_authorization_header_leak(self) -> None:
        """Отсутствует утечка токена в заголовках."""
        response = HttpResponse()
        access_token = 'sensitive_token'

        result = set_auth_cookies(response, access_token)

        for header_name, header_value in result.items():
            self.assertNotIn(access_token, str(header_value))
            self.assertNotIn(access_token, header_name)

    def test_cookie_header_format(self) -> None:
        """Формат заголовка Set-Cookie корректен."""
        response = HttpResponse()
        access_token = 'test_token'

        result = set_auth_cookies(response, access_token)

        # Проверяем, что кука была установлена
        self.assertIn(self.auth_cookie_name, result.cookies)
        cookie = result.cookies[self.auth_cookie_name]

        # Проверяем атрибуты куки
        self.assertTrue(cookie['httponly'])
        self.assertEqual(
            cookie['samesite'],
            settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE'],
        )
        self.assertEqual(cookie.value, access_token)

    def test_cookie_header_security_attributes(self) -> None:
        """Все атрибуты безопасности присутствуют в заголовке."""
        response = HttpResponse()
        access_token = 'test_token'

        result = set_auth_cookies(response, access_token)

        # Проверяем, что кука была установлена
        self.assertIn(self.auth_cookie_name, result.cookies)
        cookie = result.cookies[self.auth_cookie_name]

        # Проверяем атрибуты безопасности
        self.assertTrue(cookie['httponly'])
        self.assertEqual(
            cookie['samesite'],
            settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE'],
        )
        self.assertEqual(
            cookie['path'],
            settings.SIMPLE_JWT['AUTH_COOKIE_PATH'],
        )
        self.assertEqual(
            bool(cookie['secure']),
            settings.SIMPLE_JWT['AUTH_COOKIE_SECURE'],
        )


if __name__ == '__main__':
    unittest.main()
