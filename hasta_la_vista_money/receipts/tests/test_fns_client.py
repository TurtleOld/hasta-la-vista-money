"""Tests for safe, actionable FNS HTTP diagnostics."""

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import httpx
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from hasta_la_vista_money.receipts.services.fns_client import (
    FNSClient,
    FNSCredentials,
    FNSTemporaryUnavailableError,
    FNSTimeoutError,
)

TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    },
}


def _http_client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[..., httpx.Client]:
    transport = httpx.MockTransport(handler)

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=transport, **kwargs)

    return factory


@override_settings(CACHES=TEST_CACHES)
class FNSClientDiagnosticTests(SimpleTestCase):
    """HTTP failures explain the stage without leaking credentials."""

    def setUp(self) -> None:
        cache.clear()
        self.credentials = FNSCredentials(
            inn='123456789012',
            password='super-secret-password',
            client_secret='client-secret-value',
        )

    def _client(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
    ) -> FNSClient:
        return FNSClient(
            http_client_factory=_http_client_factory(handler),
            base_url='https://fns.example/v2',
            credentials=self.credentials,
            timeout_seconds=1,
            poll_attempts=1,
            poll_interval_seconds=0,
        )

    def test_auth_http_error_logs_actionable_safe_diagnostics(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=500,
                json={
                    'code': 'AUTH_FAILED',
                    'message': 'Client fingerprint is no longer accepted',
                    'inn': self.credentials.inn,
                    'password': self.credentials.password,
                    'client_secret': self.credentials.client_secret,
                },
                headers={
                    'content-type': 'application/json',
                    'retry-after': '30',
                    'x-request-id': 'fns-request-123',
                },
                request=request,
            )

        with (
            patch(
                'hasta_la_vista_money.receipts.services.fns_client.'
                'logger.warning',
            ) as warning,
            self.assertRaises(FNSTemporaryUnavailableError),
        ):
            self._client(handler).fetch_receipt('qr')

        warning.assert_called_once()
        event = warning.call_args.args[0]
        context = warning.call_args.kwargs
        self.assertEqual(event, 'fns_http_request_failed')
        self.assertEqual(context['failure_stage'], 'authentication')
        self.assertEqual(
            context['failure_category'],
            'authentication_endpoint_error',
        )
        self.assertEqual(context['status_code'], 500)
        self.assertEqual(
            context['response_headers'],
            {
                'retry-after': '30',
                'x-request-id': 'fns-request-123',
            },
        )
        self.assertEqual(
            context['response_diagnostics'],
            {
                'code': 'AUTH_FAILED',
                'message': 'Client fingerprint is no longer accepted',
            },
        )
        serialized_context = repr(context)
        self.assertNotIn(self.credentials.inn, serialized_context)
        self.assertNotIn(self.credentials.password, serialized_context)
        self.assertNotIn(self.credentials.client_secret, serialized_context)

    def test_plain_text_error_redacts_configured_secrets(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = (
                f'Auth failed for {self.credentials.inn}; '
                f'password={self.credentials.password}; '
                f'client_secret={self.credentials.client_secret}'
            )
            return httpx.Response(
                status_code=502,
                text=body,
                headers={'content-type': 'text/plain'},
                request=request,
            )

        with (
            patch(
                'hasta_la_vista_money.receipts.services.fns_client.'
                'logger.warning',
            ) as warning,
            self.assertRaises(FNSTemporaryUnavailableError),
        ):
            self._client(handler).fetch_receipt('qr')

        context = warning.call_args.kwargs
        self.assertEqual(context['response_type'], 'text')
        self.assertEqual(
            context['response_excerpt'].count('[REDACTED]'),
            3,
        )
        serialized_context = repr(context)
        self.assertNotIn(self.credentials.inn, serialized_context)
        self.assertNotIn(self.credentials.password, serialized_context)
        self.assertNotIn(self.credentials.client_secret, serialized_context)

    def test_timeout_logs_endpoint_stage_and_duration(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout('FNS read timed out', request=request)

        with (
            patch(
                'hasta_la_vista_money.receipts.services.fns_client.'
                'logger.warning',
            ) as warning,
            self.assertRaises(FNSTimeoutError),
        ):
            self._client(handler).fetch_receipt('qr')

        warning.assert_called_once()
        event = warning.call_args.args[0]
        context = warning.call_args.kwargs
        self.assertEqual(event, 'fns_http_timeout')
        self.assertEqual(context['failure_stage'], 'authentication')
        self.assertEqual(context['exception_type'], 'ReadTimeout')
        self.assertGreaterEqual(context['duration_ms'], 0)
