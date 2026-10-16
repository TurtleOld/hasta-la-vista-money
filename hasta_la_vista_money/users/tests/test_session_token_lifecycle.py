from typing import Final

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from hasta_la_vista_money import constants

User = get_user_model()

OLD_PASSWORD: Final = 'old-secret-pass-123'
NEW_PASSWORD: Final = 'new-secret-pass-456'


class SessionTokenLifecycleTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='lifecycle-user',
            password=OLD_PASSWORD,
        )
        self.client.force_login(self.user)

    def _set_refresh_cookie(self) -> RefreshToken:
        refresh = RefreshToken.for_user(self.user)
        cookie_name = str(settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH'])
        self.client.cookies[cookie_name] = str(refresh)
        return refresh

    def test_logout_blacklists_refresh_token(self) -> None:
        refresh = self._set_refresh_cookie()
        self.client.post(reverse('logout'))
        with self.assertRaises(TokenError):
            RefreshToken(str(refresh))  # type: ignore[arg-type]

    def test_password_change_requires_old_password(self) -> None:
        response = self.client.post(
            reverse('users:password'),
            {
                'old_password': 'wrong-old-password',
                'new_password1': NEW_PASSWORD,
                'new_password2': NEW_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_password_change_without_old_password_fails(self) -> None:
        self.client.post(
            reverse('users:password'),
            {
                'new_password1': NEW_PASSWORD,
                'new_password2': NEW_PASSWORD,
            },
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_password_change_with_old_password_succeeds(self) -> None:
        response = self.client.post(
            reverse('users:password'),
            {
                'old_password': OLD_PASSWORD,
                'new_password1': NEW_PASSWORD,
                'new_password2': NEW_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertIn('_auth_user_id', self.client.session)

    def test_password_change_blacklists_outstanding_refresh_tokens(
        self,
    ) -> None:
        refresh = self._set_refresh_cookie()
        self.client.post(
            reverse('users:password'),
            {
                'old_password': OLD_PASSWORD,
                'new_password1': NEW_PASSWORD,
                'new_password2': NEW_PASSWORD,
            },
        )
        with self.assertRaises(TokenError):
            RefreshToken(str(refresh))  # type: ignore[arg-type]

    def test_session_cookie_age_is_thirty_days(self) -> None:
        self.assertEqual(constants.SESSION_COOKIE_AGE, 60 * 60 * 24 * 30)

    def test_logout_ignores_invalid_refresh_cookie(self) -> None:
        cookie_name = str(settings.SIMPLE_JWT['AUTH_COOKIE_REFRESH'])
        self.client.cookies[cookie_name] = 'not-a-token'
        response = self.client.post(reverse('logout'))
        self.assertEqual(response.status_code, 302)
