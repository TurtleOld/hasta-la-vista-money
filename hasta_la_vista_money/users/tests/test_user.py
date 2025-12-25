from typing import ClassVar

from django.test import Client, TestCase
from django.urls import reverse_lazy
from faker import Faker

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User

LENGTH_PASSWORD: int = 12


class TestUser(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']  # type: ignore[misc]

    def setUp(self) -> None:
        self.user1: User = User.objects.get(pk=1)
        self.user2: User = User.objects.get(pk=2)
        self.client: Client = Client()
        self.faker: Faker = Faker()

    def test_create_user(self) -> None:
        self.client.force_login(self.user1)
        self.client.force_login(self.user2)
        url = reverse_lazy('users:registration')
        response = self.client.get(url)
        self.assertEqual(response.status_code, constants.REDIRECTS)

        Faker.seed(0)
        username: str = self.faker.user_name()
        first_name: str = self.faker.first_name()
        last_name: str = self.faker.last_name()
        email: str = self.faker.email()
        set_password: str = self.faker.password(length=LENGTH_PASSWORD)
        new_user: dict[str, str | bool] = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'policy': True,
            'username': username,
            'password1': set_password,
            'password2': set_password,
        }

        response = self.client.post(url, new_user, follow=True)
        self.assertRedirects(response, '/hasta-la-vista-money/')

    def test_login_user_success(self) -> None:
        self.client.force_login(self.user1)

        user: User = User.objects.get(username=self.user1)
        self.assertTrue(user.is_authenticated)

    def test_login_user_redirect_after_success(self) -> None:
        """Test successful redirect after login."""
        url = reverse_lazy('login')
        self.user1.set_password('testpassword')
        self.user1.save()

        response = self.client.post(
            url,
            {
                'username': str(self.user1.username),
                'password': 'testpassword',
            },
            follow=False,
        )

        self.assertEqual(response.status_code, constants.REDIRECTS)
        self.assertRedirects(response, '/hasta-la-vista-money/')

    def test_login_user_invalid_credentials(self) -> None:
        url = reverse_lazy('login')
        response = self.client.post(
            url,
            {
                'username': 'testuser',
                'password': 'wrongpassword',
            },
        )

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

        self.assertContains(
            response,
            'Пожалуйста, введите правильные имя пользователя и пароль.',
        )

        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_login_user_empty_fields(self) -> None:
        url = reverse_lazy('login')
        response = self.client.post(
            url,
            {
                'username': '',
                'password': '',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Пожалуйста, введите имя пользователя или email.',
        )
        self.assertFalse(response.wsgi_request.user.is_authenticated)
