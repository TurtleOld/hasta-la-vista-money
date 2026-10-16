from django.test import RequestFactory, TestCase
from rest_framework.request import Request
from structlog.testing import capture_logs

from hasta_la_vista_money.authentication.authentication import (
    CookieJWTAuthentication,
)


class AuthorizationHeaderLoggingTest(TestCase):
    def test_unsupported_header_value_is_not_logged(self) -> None:
        raw = RequestFactory().get(
            '/api/x/',
            HTTP_AUTHORIZATION='Basic dXNlcjpzZWNyZXQ=',
        )
        with capture_logs() as logs:
            result = CookieJWTAuthentication()._authenticate_from_header(
                Request(raw),
            )

        self.assertIsNone(result)
        self.assertTrue(logs)
        self.assertNotIn('dXNlcjpzZWNyZXQ', repr(logs))
