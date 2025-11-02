from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from hasta_la_vista_money.api.throttling import (
    AnonLoginRateThrottle,
    LoginRateThrottle,
)
from hasta_la_vista_money.users.models import User


class LoginRateThrottleTestCase(TestCase):
    """Тесты для класса LoginRateThrottle."""

    def setUp(self) -> None:
        """Настройка тестовых данных."""
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_scope_attribute(self) -> None:
        """Тест проверки атрибута scope."""
        LoginRateThrottle.THROTTLE_RATES = {'login': '5/min'}
        throttle = LoginRateThrottle()
        self.assertEqual(throttle.scope, 'login')

    def test_get_cache_key_with_authenticated_user(self) -> None:
        """Тест получения ключа кэша для аутентифицированного пользователя."""
        LoginRateThrottle.THROTTLE_RATES = {'login': '5/min'}
        throttle = LoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = self.user

        cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

        self.assertIsNotNone(cache_key)
        assert cache_key is not None
        self.assertIn('login', cache_key)
        self.assertIn(str(self.user.pk), cache_key)

    def test_get_cache_key_with_anonymous_user(self) -> None:
        """Тест получения ключа кэша для анонимного пользователя."""
        LoginRateThrottle.THROTTLE_RATES = {'login': '5/min'}
        throttle = LoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = Mock()
        request.user.is_authenticated = False

        with patch.object(throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'anonymous_ident'

            cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

            self.assertIsNotNone(cache_key)
            assert cache_key is not None
            self.assertIn('login', cache_key)
            self.assertIn('anonymous_ident', cache_key)

    def test_login_throttle_blocks_after_limit(self) -> None:
        """Проверяет, что после двух запросов следующий блокируется."""
        LoginRateThrottle.THROTTLE_RATES = {'login': '2/min'}
        throttle = LoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = self.user

        cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]
        throttle.cache.delete(cache_key)

        allowed1 = throttle.allow_request(request, None)  # type: ignore[arg-type]
        allowed2 = throttle.allow_request(request, None)  # type: ignore[arg-type]
        allowed3 = throttle.allow_request(request, None)  # type: ignore[arg-type]

        self.assertTrue(allowed1)
        self.assertTrue(allowed2)
        self.assertFalse(allowed3)
        wait_time = throttle.wait()
        assert wait_time is not None
        self.assertGreater(wait_time, 0)

        throttle.cache.delete(cache_key)


class AnonLoginRateThrottleTestCase(TestCase):
    """Тесты для класса AnonLoginRateThrottle."""

    def setUp(self) -> None:
        """Настройка тестовых данных."""
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_scope_attribute(self) -> None:
        """Тест проверки атрибута scope."""
        AnonLoginRateThrottle.THROTTLE_RATES = {'anon': '5/min'}
        throttle = AnonLoginRateThrottle()
        self.assertEqual(throttle.scope, 'anon')

    def test_get_cache_key_with_authenticated_user(self) -> None:
        """Тест что аутентифицированные пользователи не ограничиваются."""
        AnonLoginRateThrottle.THROTTLE_RATES = {'anon': '5/min'}
        throttle = AnonLoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = self.user

        cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

        self.assertIsNone(cache_key)

    def test_get_cache_key_with_anonymous_user(self) -> None:
        """Тест получения ключа кэша для анонимного пользователя."""
        AnonLoginRateThrottle.THROTTLE_RATES = {'anon': '5/min'}
        throttle = AnonLoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = Mock()
        request.user.is_authenticated = False

        with patch.object(throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'anonymous_ident'

            cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

            self.assertIsNotNone(cache_key)
            assert cache_key is not None
            self.assertIn('anon', cache_key)
            self.assertIn('anonymous_ident', cache_key)

    def test_get_cache_key_with_unauthenticated_user(self) -> None:
        """Тест получения ключа кэша для неаутентифицированного пользователя."""
        AnonLoginRateThrottle.THROTTLE_RATES = {'anon': '5/min'}
        throttle = AnonLoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        anonymous = AnonymousUser()
        request.user = anonymous  # type: ignore[assignment]

        with patch.object(throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'unauthenticated_ident'

            cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

            self.assertIsNotNone(cache_key)
            assert cache_key is not None
            self.assertIn('anon', cache_key)
            self.assertIn('unauthenticated_ident', cache_key)

    def test_anon_throttle_blocks_after_limit(self) -> None:
        """Проверяет, что после двух
        анонимных запросов следующий блокируется."""
        AnonLoginRateThrottle.THROTTLE_RATES = {'anon': '2/min'}
        throttle = AnonLoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = Mock()
        request.user.is_authenticated = False

        with patch.object(throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'ident'

            cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]
            throttle.cache.delete(cache_key)

            allowed1 = throttle.allow_request(request, None)  # type: ignore[arg-type]
            allowed2 = throttle.allow_request(request, None)  # type: ignore[arg-type]
            allowed3 = throttle.allow_request(request, None)  # type: ignore[arg-type]

            self.assertTrue(allowed1)
            self.assertTrue(allowed2)
            self.assertFalse(allowed3)
            wait_time = throttle.wait()
            assert wait_time is not None
            self.assertGreater(wait_time, 0)

            throttle.cache.delete(cache_key)
