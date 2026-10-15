from typing import Final

from axes.handlers.proxy import AxesProxyHandler
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.http import HttpRequest
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import AnonRateThrottle

from hasta_la_vista_money.core.client_ip import get_client_ip
from hasta_la_vista_money.users.factories import UserFactoryTyped

FAILURE_LIMIT: Final = 5
PROXY_ADDR: Final = '172.18.0.2'
CLIENT_ADDR: Final = '203.0.113.7'
SPOOFED_FORWARDED_FOR: Final = f'6.6.6.6, {CLIENT_ADDR}'


@override_settings(TRUSTED_PROXY_COUNT=1)
class ClientIpTest(TestCase):
    def test_uses_address_added_by_trusted_proxy(self) -> None:
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR=PROXY_ADDR,
            HTTP_X_FORWARDED_FOR=SPOOFED_FORWARDED_FOR,
        )
        self.assertEqual(get_client_ip(request), CLIENT_ADDR)

    def test_falls_back_to_remote_addr_without_header(self) -> None:
        request = RequestFactory().get('/', REMOTE_ADDR=PROXY_ADDR)
        self.assertEqual(get_client_ip(request), PROXY_ADDR)

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_ignores_header_without_proxy(self) -> None:
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR=PROXY_ADDR,
            HTTP_X_FORWARDED_FOR=SPOOFED_FORWARDED_FOR,
        )
        self.assertEqual(get_client_ip(request), PROXY_ADDR)


@override_settings(
    AXES_ENABLED=True,
    AXES_FAILURE_LIMIT=FAILURE_LIMIT,
    AXES_CLIENT_IP_CALLABLE='hasta_la_vista_money.core.client_ip.get_client_ip',
    TRUSTED_PROXY_COUNT=1,
)
class AxesLockoutTest(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        self.first = UserFactoryTyped(username='first-user')
        self.second = UserFactoryTyped(username='second-user')

    def _request(self, client_ip: str) -> HttpRequest:
        request = RequestFactory().post(
            reverse('login'),
            REMOTE_ADDR=PROXY_ADDR,
            HTTP_X_FORWARDED_FOR=client_ip,
        )
        request.session = self.client.session
        return request

    def _fail_login(self, username: str, client_ip: str) -> None:
        authenticate(
            request=self._request(client_ip),
            username=username,
            password='wrong-password',
        )

    def _is_allowed(self, username: str, client_ip: str) -> bool:
        return bool(
            AxesProxyHandler.is_allowed(
                self._request(client_ip),
                {'username': username},
            ),
        )

    def test_lockout_is_per_username_and_ip(self) -> None:
        for _ in range(FAILURE_LIMIT):
            self._fail_login(self.first.username, CLIENT_ADDR)

        self.assertFalse(self._is_allowed(self.first.username, CLIENT_ADDR))
        self.assertTrue(self._is_allowed(self.second.username, CLIENT_ADDR))
        self.assertTrue(self._is_allowed(self.first.username, '203.0.113.8'))


class DrfThrottleIdentTest(TestCase):
    def _ident(self) -> str:
        request = APIRequestFactory().get(
            '/',
            REMOTE_ADDR=PROXY_ADDR,
            HTTP_X_FORWARDED_FOR=SPOOFED_FORWARDED_FOR,
        )
        return AnonRateThrottle().get_ident(request)

    @override_settings(REST_FRAMEWORK={'NUM_PROXIES': 1})
    def test_spoofed_forwarded_for_is_ignored(self) -> None:
        self.assertEqual(self._ident(), CLIENT_ADDR)
