from collections.abc import Sequence

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()
TEST_PASSWORD = 'testpassword'  # nosec B105
DEFAULT_URL = '/finance_account/'


class LoginRedirectTest(TestCase):
    """Login must not redirect to untrusted `next` URLs."""

    fixtures: Sequence[str] = ['users.yaml']

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            self.fail('No user found in fixtures')
        self.user = user
        self.user.set_password(TEST_PASSWORD)
        self.user.save()
        self.url = reverse('login')

    def _post_login(self, next_url: str) -> str:
        response = self.client.post(
            self.url,
            {
                'username': self.user.get_username(),
                'password': TEST_PASSWORD,
                'next': next_url,
            },
        )
        self.assertEqual(response.status_code, 302)
        return str(response['Location'])

    def test_post_external_next_falls_back_to_default(self) -> None:
        location = self._post_login('https://evil.example/x')
        self.assertEqual(location, DEFAULT_URL)

    def test_post_protocol_relative_next_falls_back_to_default(self) -> None:
        location = self._post_login('//evil.example')
        self.assertEqual(location, DEFAULT_URL)

    def test_post_local_next_is_preserved(self) -> None:
        location = self._post_login('/finance_account/')
        self.assertEqual(location, '/finance_account/')

    def test_authenticated_get_external_next_falls_back_to_default(
        self,
    ) -> None:
        self.client.force_login(self.user)
        response = self.client.get(
            self.url,
            {'next': 'https://evil.example/x'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], DEFAULT_URL)

    def test_authenticated_get_protocol_relative_next_falls_back(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(self.url, {'next': '//evil.example'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], DEFAULT_URL)
