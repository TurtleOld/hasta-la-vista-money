from typing import cast

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.middleware import CheckAdminMiddleware

User = get_user_model()


class CheckAdminMiddlewareTest(TestCase):
    """Tests for CheckAdminMiddleware access blocking."""

    def setUp(self) -> None:
        self.factory: RequestFactory = RequestFactory()
        self.middleware: CheckAdminMiddleware = CheckAdminMiddleware(  # type: ignore[no-untyped-call]
            get_response=lambda r: r,
        )
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    def test_no_superuser_blocks_access_to_protected_pages(self) -> None:
        User.objects.all().delete()

        protected_paths: list[str] = [
            '/',
            '/budget/',
            '/expense/',
            '/income/',
            '/finance-account/',
            '/receipts/',
            '/users/profile/',
            '/users/statistics/',
        ]

        for path in protected_paths:
            with self.subTest(path=path):
                request: HttpRequest = self.factory.get(path)
                response: HttpResponse | HttpRequest = self.middleware(request)
                response_redirect: HttpResponseRedirect = cast(
                    'HttpResponseRedirect',
                    response,
                )

                self.assertEqual(
                    response_redirect.status_code,
                    constants.REDIRECTS,
                )
                self.assertEqual(
                    response_redirect.url,
                    reverse('users:registration'),
                )

    def test_no_superuser_allows_access_to_registration(self) -> None:
        User.objects.all().delete()

        registration_path: str = reverse('users:registration')
        request: HttpRequest = self.factory.get(registration_path)
        response: HttpResponse | HttpRequest = self.middleware(request)

        self.assertEqual(response, request)

    def test_with_superuser_allows_access_to_all_pages(self) -> None:
        User.objects.create_superuser(  # type: ignore[attr-defined]
            username='admin',
            email='admin@example.com',
            password='admin123',
        )

        protected_paths: list[str] = [
            '/',
            '/budget/',
            '/expense/',
            '/income/',
            '/finance-account/',
            '/receipts/',
            '/users/profile/',
            '/users/statistics/',
            reverse('users:registration'),
        ]

        for path in protected_paths:
            with self.subTest(path=path):
                request: HttpRequest = self.factory.get(path)
                response: HttpResponse | HttpRequest = self.middleware(request)

                self.assertEqual(response, request)

    def test_cache_is_used_to_avoid_database_queries(self) -> None:
        User.objects.all().delete()

        request1: HttpRequest = self.factory.get('/')
        with self.assertNumQueries(1):
            self.middleware(request1)

        request2: HttpRequest = self.factory.get('/budget/')
        with self.assertNumQueries(0):
            self.middleware(request2)

        cached_value: bool | None = cache.get('has_superuser')
        self.assertIsNotNone(cached_value)
        self.assertFalse(cached_value)

    def test_cache_updates_when_superuser_created(self) -> None:
        User.objects.all().delete()

        request1: HttpRequest = self.factory.get('/')
        response1: HttpResponse | HttpRequest = self.middleware(request1)
        response1_redirect: HttpResponseRedirect = cast(
            'HttpResponseRedirect',
            response1,
        )
        self.assertEqual(response1_redirect.status_code, constants.REDIRECTS)

        cache.clear()

        User.objects.create_superuser(  # type: ignore[attr-defined]
            username='admin',
            email='admin@example.com',
            password='admin123',
        )

        request2: HttpRequest = self.factory.get('/')
        response2: HttpResponse | HttpRequest = self.middleware(request2)
        self.assertEqual(response2, request2)

    def test_regular_user_does_not_prevent_redirect(self) -> None:
        User.objects.all().delete()
        User.objects.create_user(  # type: ignore[attr-defined]
            username='regular',
            email='regular@example.com',
            password='regular123',
        )

        request: HttpRequest = self.factory.get('/')
        response: HttpResponse | HttpRequest = self.middleware(request)
        response_redirect: HttpResponseRedirect = cast(
            'HttpResponseRedirect',
            response,
        )

        self.assertEqual(response_redirect.status_code, constants.REDIRECTS)
        self.assertEqual(response_redirect.url, reverse('users:registration'))

    def test_staff_user_without_superuser_does_not_prevent_redirect(
        self,
    ) -> None:
        User.objects.all().delete()
        User.objects.create_user(  # type: ignore[attr-defined]
            username='staff',
            email='staff@example.com',
            password='staff123',
            is_staff=True,
        )

        request: HttpRequest = self.factory.get('/')
        response: HttpResponse | HttpRequest = self.middleware(request)
        response_redirect: HttpResponseRedirect = cast(
            'HttpResponseRedirect',
            response,
        )

        self.assertEqual(response_redirect.status_code, constants.REDIRECTS)
        self.assertEqual(response_redirect.url, reverse('users:registration'))


@override_settings(
    MIDDLEWARE=[
        'django.middleware.security.SecurityMiddleware',
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.middleware.common.CommonMiddleware',
        'django.middleware.csrf.CsrfViewMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'django.contrib.messages.middleware.MessageMiddleware',
        'django.middleware.clickjacking.XFrameOptionsMiddleware',
        'hasta_la_vista_money.users.middleware.CheckAdminMiddleware',
    ],
)
class CheckAdminMiddlewareIntegrationTest(TestCase):
    """Integration tests for CheckAdminMiddleware
    in Django request/response cycle."""

    def setUp(self) -> None:
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    def test_no_superuser_integration_redirects_to_registration(self) -> None:
        User.objects.all().delete()

        response = self.client.get('/')

        self.assertEqual(response.status_code, constants.REDIRECTS)
        self.assertRedirects(
            response,
            reverse('users:registration'),
            fetch_redirect_response=False,
        )

    def test_no_superuser_integration_allows_registration(self) -> None:
        User.objects.all().delete()

        response = self.client.get(reverse('users:registration'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_with_superuser_integration_allows_access(self) -> None:
        cache.clear()
        User.objects.create_superuser(  # type: ignore[attr-defined]
            username='admin',
            email='admin@example.com',
            password='admin123',
        )

        response = self.client.get('/')

        if response.status_code == constants.REDIRECTS:
            self.assertNotEqual(
                response.url,  # type: ignore[attr-defined]
                reverse('users:registration'),
                msg='Не должно быть редиректа на регистрацию '
                'при наличии суперпользователя',
            )
        else:
            expected_codes: list[int] = [200, 301]
            self.assertIn(
                response.status_code,
                expected_codes,
                msg=f'Ожидался статус 200 или 301, '
                f'получен {response.status_code}',
            )

    def test_cannot_bypass_protection_with_direct_url_manipulation(
        self,
    ) -> None:
        User.objects.all().delete()

        bypass_attempts: list[str] = [
            '/users/profile/',
            '/expense/create/',
            '/income/create/',
            '/finance-account/create/',
        ]

        for path in bypass_attempts:
            with self.subTest(path=path):
                response = self.client.get(path, follow=False)

                self.assertEqual(response.status_code, constants.REDIRECTS)
                self.assertIsInstance(
                    response,
                    HttpResponseRedirect,
                    msg='Response should be HttpResponseRedirect',
                )
                assert isinstance(response, HttpResponseRedirect)
                self.assertEqual(
                    response.url,  # type: ignore[attr-defined]
                    reverse('users:registration'),
                )
