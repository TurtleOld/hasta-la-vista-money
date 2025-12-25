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
    """Test cases for LoginRateThrottle class.

    Tests rate limiting for login requests including authenticated
    and anonymous users.
    """

    def setUp(self) -> None:
        """Set up test data."""
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_scope_attribute(self) -> None:
        """Test scope attribute."""
        LoginRateThrottle.THROTTLE_RATES = {'login': '5/min'}
        throttle = LoginRateThrottle()
        self.assertEqual(throttle.scope, 'login')

    def test_get_cache_key_with_authenticated_user(self) -> None:
        """Test cache key generation for authenticated user."""
        LoginRateThrottle.THROTTLE_RATES = {'login': '5/min'}
        throttle = LoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = self.user

        cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

        self.assertIsNotNone(cache_key)
        if cache_key is None:
            msg = 'cache_key should not be None'
            raise ValueError(msg)
        self.assertIn('login', cache_key)
        self.assertIn(str(self.user.pk), cache_key)

    def test_get_cache_key_with_anonymous_user(self) -> None:
        """Test cache key generation for anonymous user."""
        LoginRateThrottle.THROTTLE_RATES = {'login': '5/min'}
        throttle = LoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = Mock()
        request.user.is_authenticated = False

        with patch.object(throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'anonymous_ident'

            cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

            self.assertIsNotNone(cache_key)
            if cache_key is None:
                msg = 'cache_key should not be None'
                raise ValueError(msg)
            self.assertIn('login', cache_key)
            self.assertIn('anonymous_ident', cache_key)

    def test_login_throttle_blocks_after_limit(self) -> None:
        """Test that requests are blocked after rate limit is exceeded."""
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
        self.assertIsNotNone(wait_time)
        if wait_time is None:
            msg = 'wait_time should not be None'
            raise ValueError(msg)
        self.assertGreater(wait_time, 0)

        throttle.cache.delete(cache_key)


class AnonLoginRateThrottleTestCase(TestCase):
    """Test cases for AnonLoginRateThrottle class.

    Tests rate limiting for anonymous login requests.
    """

    def setUp(self) -> None:
        """Set up test data."""
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_scope_attribute(self) -> None:
        """Test scope attribute."""
        AnonLoginRateThrottle.THROTTLE_RATES = {'anon': '5/min'}
        throttle = AnonLoginRateThrottle()
        self.assertEqual(throttle.scope, 'anon')

    def test_get_cache_key_with_authenticated_user(self) -> None:
        """Test that authenticated users are not throttled."""
        AnonLoginRateThrottle.THROTTLE_RATES = {'anon': '5/min'}
        throttle = AnonLoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = self.user

        cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

        self.assertIsNone(cache_key)

    def test_get_cache_key_with_anonymous_user(self) -> None:
        """Test cache key generation for anonymous user."""
        AnonLoginRateThrottle.THROTTLE_RATES = {'anon': '5/min'}
        throttle = AnonLoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        request.user = Mock()
        request.user.is_authenticated = False

        with patch.object(throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'anonymous_ident'

            cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

            self.assertIsNotNone(cache_key)
            if cache_key is None:
                msg = 'cache_key should not be None'
                raise ValueError(msg)
            self.assertIn('anon', cache_key)
            self.assertIn('anonymous_ident', cache_key)

    def test_get_cache_key_with_unauthenticated_user(self) -> None:
        """Test cache key generation for unauthenticated user."""
        AnonLoginRateThrottle.THROTTLE_RATES = {'anon': '5/min'}
        throttle = AnonLoginRateThrottle()
        request = self.factory.post('/api/auth/token/')
        anonymous = AnonymousUser()
        request.user = anonymous

        with patch.object(throttle, 'get_ident') as mock_get_ident:
            mock_get_ident.return_value = 'unauthenticated_ident'

            cache_key = throttle.get_cache_key(request, None)  # type: ignore[arg-type]

            self.assertIsNotNone(cache_key)
            if cache_key is None:
                msg = 'cache_key should not be None'
                raise ValueError(msg)
            self.assertIn('anon', cache_key)
            self.assertIn('unauthenticated_ident', cache_key)

    def test_anon_throttle_blocks_after_limit(self) -> None:
        """Test that anonymous requests are blocked after rate limit."""
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
            self.assertIsNotNone(wait_time)
            if wait_time is None:
                msg = 'wait_time should not be None'
                raise ValueError(msg)
            self.assertGreater(wait_time, 0)

            throttle.cache.delete(cache_key)
