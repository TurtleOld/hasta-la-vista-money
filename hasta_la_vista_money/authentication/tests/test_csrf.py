from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import AccessToken

from hasta_la_vista_money.finance_account.factories import AccountFactory
from hasta_la_vista_money.users.factories import UserFactoryTyped

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import Account


class CookieJWTCsrfTestCase(TestCase):
    """CSRF is enforced only when the JWT comes from a cookie."""

    def setUp(self) -> None:
        self.user = UserFactoryTyped()
        self.account = cast('Account', AccountFactory(user=self.user))
        self.token = str(AccessToken.for_user(self.user))
        self.url = reverse(
            'finance_account:api_detail',
            kwargs={'pk': self.account.pk},
        )
        self.client = Client(enforce_csrf_checks=True)
        self.payload = '{"name_account": "Renamed"}'

    def _set_auth_cookie(self) -> None:
        self.client.cookies[str(settings.SIMPLE_JWT['AUTH_COOKIE'])] = (
            self.token
        )

    def test_cookie_jwt_patch_without_csrf_forbidden(self) -> None:
        self._set_auth_cookie()
        response = self.client.patch(
            self.url,
            self.payload,
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cookie_jwt_patch_with_csrf_ok(self) -> None:
        self._set_auth_cookie()
        csrf_token = get_token(self._request_stub())
        self.client.cookies[settings.CSRF_COOKIE_NAME] = csrf_token
        response = self.client.patch(
            self.url,
            self.payload,
            content_type='application/json',
            headers={'x-csrftoken': csrf_token},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_bearer_jwt_patch_without_csrf_ok(self) -> None:
        response = self.client.patch(
            self.url,
            self.payload,
            content_type='application/json',
            headers={'authorization': f'Bearer {self.token}'},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cookie_jwt_get_without_csrf_ok(self) -> None:
        self._set_auth_cookie()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @staticmethod
    def _request_stub() -> HttpRequest:
        request = HttpRequest()
        request.META['CSRF_COOKIE_NEEDS_UPDATE'] = False
        return request
