from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.middleware import CheckAdminMiddleware

User = get_user_model()


class CheckAdminMiddlewareTest(TestCase):
    """
    Тесты для CheckAdminMiddleware, проверяющие блокировку доступа
    к приложению при отсутствии суперпользователя.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CheckAdminMiddleware(get_response=lambda r: r)
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_no_superuser_blocks_access_to_protected_pages(self):
        """
        При отсутствии суперпользователя доступ к защищённым страницам
        должен быть заблокирован с редиректом на регистрацию.
        """
        User.objects.all().delete()

        protected_paths = [
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
                request = self.factory.get(path)
                response = self.middleware(request)

                self.assertEqual(response.status_code, constants.REDIRECTS)
                self.assertEqual(
                    response.url,
                    reverse('users:registration'),
                )

    def test_no_superuser_allows_access_to_registration(self):
        """
        При отсутствии суперпользователя страница регистрации
        должна быть доступна.
        """
        User.objects.all().delete()

        registration_path = reverse('users:registration')
        request = self.factory.get(registration_path)
        response = self.middleware(request)

        self.assertEqual(response, request)

    def test_with_superuser_allows_access_to_all_pages(self):
        """
        При наличии суперпользователя доступ ко всем страницам
        должен быть разрешён.
        """
        User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin123',  # noqa: S106
        )

        protected_paths = [
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
                request = self.factory.get(path)
                response = self.middleware(request)

                self.assertEqual(response, request)

    def test_cache_is_used_to_avoid_database_queries(self):
        """
        Middleware должен использовать кэш для минимизации
        запросов к базе данных.
        """
        User.objects.all().delete()

        request1 = self.factory.get('/')
        with self.assertNumQueries(1):
            self.middleware(request1)

        request2 = self.factory.get('/budget/')
        with self.assertNumQueries(0):
            self.middleware(request2)

        cached_value = cache.get('has_superuser')
        self.assertIsNotNone(cached_value)
        self.assertFalse(cached_value)

    def test_cache_updates_when_superuser_created(self):
        """
        При создании суперпользователя кэш должен обновиться
        после истечения TTL.
        """
        User.objects.all().delete()

        request1 = self.factory.get('/')
        response1 = self.middleware(request1)
        self.assertEqual(response1.status_code, constants.REDIRECTS)

        cache.clear()

        User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin123',  # noqa: S106
        )

        request2 = self.factory.get('/')
        response2 = self.middleware(request2)
        self.assertEqual(response2, request2)

    def test_regular_user_does_not_prevent_redirect(self):
        """
        Наличие обычного пользователя (не суперпользователя)
        не должно предотвращать редирект на регистрацию.
        """
        User.objects.all().delete()
        User.objects.create_user(
            username='regular',
            email='regular@example.com',
            password='regular123',  # noqa: S106
        )

        request = self.factory.get('/')
        response = self.middleware(request)

        self.assertEqual(response.status_code, constants.REDIRECTS)
        self.assertEqual(response.url, reverse('users:registration'))

    def test_staff_user_without_superuser_does_not_prevent_redirect(self):
        """
        Наличие staff пользователя без прав суперпользователя
        не должно предотвращать редирект на регистрацию.
        """
        User.objects.all().delete()
        User.objects.create_user(
            username='staff',
            email='staff@example.com',
            password='staff123',  # noqa: S106
            is_staff=True,
        )

        request = self.factory.get('/')
        response = self.middleware(request)

        self.assertEqual(response.status_code, constants.REDIRECTS)
        self.assertEqual(response.url, reverse('users:registration'))


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
    """
    Интеграционные тесты для проверки работы middleware
    в реальном request/response цикле Django.
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_no_superuser_integration_redirects_to_registration(self):
        """
        Интеграционный тест: при отсутствии суперпользователя
        запросы к защищённым страницам редиректят на регистрацию.
        """
        User.objects.all().delete()

        response = self.client.get('/')

        self.assertEqual(response.status_code, constants.REDIRECTS)
        self.assertRedirects(
            response,
            reverse('users:registration'),
            fetch_redirect_response=False,
        )

    def test_no_superuser_integration_allows_registration(self):
        """
        Интеграционный тест: при отсутствии суперпользователя
        страница регистрации доступна.
        """
        User.objects.all().delete()

        response = self.client.get(reverse('users:registration'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_with_superuser_integration_allows_access(self):
        """
        Интеграционный тест: при наличии суперпользователя
        доступ к страницам разрешён.
        """
        cache.clear()
        User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin123',  # noqa: S106
        )

        response = self.client.get('/')

        if response.status_code == constants.REDIRECTS:
            self.assertNotEqual(
                response.url,
                reverse('users:registration'),
                msg='Не должно быть редиректа на регистрацию '
                'при наличии суперпользователя',
            )
        else:
            expected_codes = [200, 301]
            self.assertIn(
                response.status_code,
                expected_codes,
                msg=f'Ожидался статус 200 или 301, '
                f'получен {response.status_code}',
            )

    def test_cannot_bypass_protection_with_direct_url_manipulation(self):
        """
        Нельзя обойти защиту путём прямой манипуляции с URL,
        все запросы должны проходить через middleware.
        """
        User.objects.all().delete()

        bypass_attempts = [
            '/users/profile/',
            '/expense/create/',
            '/income/create/',
            '/finance-account/create/',
        ]

        for path in bypass_attempts:
            with self.subTest(path=path):
                response = self.client.get(path, follow=False)

                self.assertEqual(response.status_code, constants.REDIRECTS)
                self.assertEqual(
                    response.url,
                    reverse('users:registration'),
                )
