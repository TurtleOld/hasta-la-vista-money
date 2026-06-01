from datetime import timedelta

import jwt
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken

from hasta_la_vista_money.api.throttling import LoginRateThrottle
from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
)
from hasta_la_vista_money.authentication.views import CookieTokenObtainPairView
from hasta_la_vista_money.users.factories import UserFactoryTyped

TEST_PASSWORD = 'testpassword123'  # nosec B105
WRONG_PASSWORD = 'wrongpassword'  # nosec B105


class CookieTokenObtainPairViewTestCase(TestCase):
    """Test cases for CookieTokenObtainPairView"""

    def setUp(self) -> None:
        """Set up test data."""
        self.client = APIClient()
        self.user = UserFactoryTyped()
        self.user.set_password(TEST_PASSWORD)
        self.user.save()
        self.url = '/authentication/token/'
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']
        self.refresh_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH']

    def test_obtain_tokens_returns_json(self) -> None:
        """Test that token obtain returns JSON with access and refresh."""
        response = self.client.post(
            self.url,
            {
                'username': self.user.username,
                'password': TEST_PASSWORD,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertTrue(response.data['success'])
        self.assertIsInstance(response.data['access'], str)
        self.assertIsInstance(response.data['refresh'], str)

    def test_obtain_tokens_sets_cookies(self) -> None:
        """Test that token obtain sets HttpOnly cookies."""
        response = self.client.post(
            self.url,
            {
                'username': self.user.username,
                'password': TEST_PASSWORD,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.auth_cookie_name, response.cookies)
        self.assertIn(self.refresh_cookie_name, response.cookies)

    def test_obtain_tokens_invalid_credentials(self) -> None:
        """Test that invalid credentials return 401."""
        response = self.client.post(
            self.url,
            {
                'username': self.user.username,
                'password': WRONG_PASSWORD,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_obtain_tokens_uses_login_rate_throttle(self) -> None:
        """Test that token obtain endpoint uses login throttling."""
        self.assertEqual(
            CookieTokenObtainPairView.throttle_classes,
            (LoginRateThrottle,),
        )

    def test_obtain_tokens_throttled_after_login_rate_limit(self) -> None:
        """Test that token obtain endpoint applies login rate limit."""
        throttle_rates = LoginRateThrottle.THROTTLE_RATES
        LoginRateThrottle.THROTTLE_RATES = {'login': '2/min'}
        cache.clear()

        try:
            response1 = self.client.post(
                self.url,
                {
                    'username': self.user.username,
                    'password': WRONG_PASSWORD,
                },
                format='json',
            )
            response2 = self.client.post(
                self.url,
                {
                    'username': self.user.username,
                    'password': WRONG_PASSWORD,
                },
                format='json',
            )
            response3 = self.client.post(
                self.url,
                {
                    'username': self.user.username,
                    'password': WRONG_PASSWORD,
                },
                format='json',
            )
        finally:
            LoginRateThrottle.THROTTLE_RATES = throttle_rates
            cache.clear()

        self.assertEqual(response1.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response2.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response3.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )


class CookieTokenRefreshViewTestCase(TestCase):
    """Test cases for CookieTokenRefreshView"""

    def setUp(self) -> None:
        """Set up test data."""
        self.client = APIClient()
        self.user = UserFactoryTyped()
        self.refresh_token = RefreshToken.for_user(self.user)
        self.url = '/authentication/token/refresh/'
        self.auth_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE']
        self.refresh_cookie_name = settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH']

    def test_refresh_from_json_body(self) -> None:
        """Test that refresh works with JSON body."""
        response = self.client.post(
            self.url,
            {'refresh': str(self.refresh_token)},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertTrue(response.data['success'])
        self.assertIsInstance(response.data['access'], str)
        self.assertIsInstance(response.data['refresh'], str)

    def test_refresh_from_json_body_no_cookie(self) -> None:
        """Test that refresh from JSON body works without cookie."""
        response = self.client.post(
            self.url,
            {'refresh': str(self.refresh_token)},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_refresh_from_cookie(self) -> None:
        """Test that refresh works with cookie."""
        self.client.cookies[self.refresh_cookie_name] = str(self.refresh_token)

        response = self.client.post(
            self.url,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertTrue(response.data['success'])

    def test_refresh_from_cookie_no_body(self) -> None:
        """Test that refresh from cookie works without JSON body."""
        self.client.cookies[self.refresh_cookie_name] = str(self.refresh_token)

        response = self.client.post(
            self.url,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_refresh_json_body_priority_over_cookie(self) -> None:
        """Test that JSON body has priority over cookie."""
        invalid_refresh = 'invalid.refresh.token'
        self.client.cookies[self.refresh_cookie_name] = invalid_refresh

        response = self.client.post(
            self.url,
            {'refresh': str(self.refresh_token)},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_refresh_always_returns_access_in_json(self) -> None:
        """Test that refresh always returns access in JSON response."""
        response = self.client.post(
            self.url,
            {'refresh': str(self.refresh_token)},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIsNotNone(response.data['access'])
        self.assertIsInstance(response.data['access'], str)

    def test_refresh_sets_cookies(self) -> None:
        """Test that refresh sets cookies."""
        response = self.client.post(
            self.url,
            {'refresh': str(self.refresh_token)},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.auth_cookie_name, response.cookies)
        self.assertIn(self.refresh_cookie_name, response.cookies)

    def test_refresh_no_token_returns_400(self) -> None:
        """Test that missing refresh token returns 400."""
        response = self.client.post(
            self.url,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertIn('No refresh token found', str(response.data['error']))

    def test_refresh_invalid_token_returns_401(self) -> None:
        """Test that invalid refresh token returns 401."""
        response = self.client.post(
            self.url,
            {'refresh': 'invalid'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('error', response.data)
        self.assertIn('Invalid refresh token', str(response.data['error']))

    def test_refresh_invalid_token_clears_cookies(self) -> None:
        """Test that invalid refresh token clears cookies."""
        self.client.cookies[self.refresh_cookie_name] = 'invalid'

        response = self.client.post(
            self.url,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        access_cookie = response.cookies.get(self.auth_cookie_name)
        refresh_cookie = response.cookies.get(self.refresh_cookie_name)
        if access_cookie:
            self.assertEqual(access_cookie.value, '')
        if refresh_cookie:
            self.assertEqual(refresh_cookie.value, '')

    def test_refresh_expired_token_returns_401(self) -> None:
        """Test that expired refresh token returns 401."""
        expired_token = RefreshToken.for_user(self.user)
        expired_payload = expired_token.payload.copy()
        expired_payload['exp'] = int(
            (timezone.now() - timedelta(days=1)).timestamp(),
        )
        expired_token_str = jwt.encode(
            expired_payload,
            settings.SECRET_KEY,
            algorithm='HS256',
        )

        response = self.client.post(
            self.url,
            {'refresh': expired_token_str},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('error', response.data)


class AuthorizationHeaderTestCase(TestCase):
    """Test cases for Authorization header support in API"""

    def setUp(self) -> None:
        """Set up test data."""
        self.client = APIClient()
        self.user = UserFactoryTyped()
        self.user.set_password(TEST_PASSWORD)
        self.user.save()

    def test_obtain_token_then_use_in_header(self) -> None:
        """Test obtaining token and using it in Authorization header."""
        obtain_response = self.client.post(
            '/authentication/token/',
            {
                'username': self.user.username,
                'password': TEST_PASSWORD,
            },
            format='json',
        )

        self.assertEqual(obtain_response.status_code, status.HTTP_200_OK)
        access_token = obtain_response.data['access']

        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {access_token}',
        )

        factory = APIRequestFactory()
        request = factory.get('/api/v1/users/groups/')
        request.META['HTTP_AUTHORIZATION'] = f'Bearer {access_token}'

        auth = CookieJWTAuthentication()
        result = auth.authenticate(request)

        self.assertIsNotNone(result)
        if result:
            user, token = result
            self.assertEqual(user, self.user)
            self.assertIsNotNone(token)
