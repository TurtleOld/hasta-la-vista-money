from typing import ClassVar

from django.test import Client, TestCase
from django.urls import reverse_lazy
from faker import Faker

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User

LENGTH_PASSWORD = 12


class TestUser(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self) -> None:
        self.user1 = User.objects.get(pk=1)
        self.user2 = User.objects.get(pk=2)
        self.client: Client = Client()
        self.faker = Faker()

    def test_create_user(self):
        self.client.force_login(self.user1)
        self.client.force_login(self.user2)
        url = reverse_lazy('users:registration')
        response = self.client.get(url)
        self.assertEqual(response.status_code, constants.REDIRECTS)

        Faker.seed(0)
        username = self.faker.user_name()
        first_name = self.faker.first_name()
        last_name = self.faker.last_name()
        email = self.faker.email()
        set_password = self.faker.password(length=LENGTH_PASSWORD)
        new_user = {
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

    def test_login_user_success(self):
        self.client.force_login(self.user1)

        user = User.objects.get(username=self.user1)
        self.assertTrue(user.is_authenticated)

    def test_login_user_invalid_credentials(self):
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

    def test_login_user_empty_fields(self):
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
