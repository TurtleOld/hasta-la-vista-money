from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from hasta_la_vista_money.api.throttling import (
    AnonLoginRateThrottle,
    LoginRateThrottle,
)
from hasta_la_vista_money.users.models import User


class LoginRateThrottleTestCase(TestCase):
    """Тесты для класса LoginRateThrottle."""

    def setUp(self):
        """Настройка тестовых данных."""
        self.throttle = LoginRateThrottle()
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_scope_attribute(self):
        """Тест проверки атрибута scope."""
        self.assertEqual(self.throttle.scope, 'login')

    def test_get_cache_key_with_authenticated_user(self):
        """Тест получения ключа кэша для аутентифицированного пользователя."""
        request = self.factory.post('/api/auth/token/')
        request.user = self.user

        cache_key = self.throttle.get_cache_key(request, None)

        self.assertIsNotNone(cache_key)
        self.assertIn('login', cache_key)
        self.assertIn(str(self.user.id), cache_key)

    def test_get_cache_key_with_anonymous_user(self):
        """Тест получения ключа кэша для анонимного пользователя."""
        request = self.factory.post('/api/auth/token/')
        request.user = Mock()
        request.user.is_authenticated = False

        with patch.object(self.throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'anonymous_ident'

            cache_key = self.throttle.get_cache_key(request, None)

            self.assertIsNotNone(cache_key)
            self.assertIn('login', cache_key)
            self.assertIn('anonymous_ident', cache_key)


class AnonLoginRateThrottleTestCase(TestCase):
    """Тесты для класса AnonLoginRateThrottle."""

    def setUp(self):
        """Настройка тестовых данных."""
        self.throttle = AnonLoginRateThrottle()
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_scope_attribute(self):
        """Тест проверки атрибута scope."""
        self.assertEqual(self.throttle.scope, 'anon_login')

    def test_get_cache_key_with_authenticated_user(self):
        """Тест что аутентифицированные пользователи не ограничиваются."""
        request = self.factory.post('/api/auth/token/')
        request.user = self.user

        cache_key = self.throttle.get_cache_key(request, None)

        self.assertIsNone(cache_key)

    def test_get_cache_key_with_anonymous_user(self):
        """Тест получения ключа кэша для анонимного пользователя."""
        request = self.factory.post('/api/auth/token/')
        request.user = Mock()
        request.user.is_authenticated = False

        with patch.object(self.throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'anonymous_ident'

            cache_key = self.throttle.get_cache_key(request, None)

            self.assertIsNotNone(cache_key)
            self.assertIn('anon_login', cache_key)
            self.assertIn('anonymous_ident', cache_key)

    def test_get_cache_key_with_unauthenticated_user(self):
        """Тест получения ключа кэша для неаутентифицированного пользователя."""
        request = self.factory.post('/api/auth/token/')
        request.user = None

        with patch.object(self.throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'unauthenticated_ident'

            cache_key = self.throttle.get_cache_key(request, None)

            self.assertIsNotNone(cache_key)
            self.assertIn('anon_login', cache_key)
            self.assertIn('unauthenticated_ident', cache_key)
