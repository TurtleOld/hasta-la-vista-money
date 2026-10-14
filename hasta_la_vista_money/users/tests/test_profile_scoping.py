from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from hasta_la_vista_money.users.models import User

GROUPS_URL = '/api/users/groups/'
AVAILABLE_GROUPS_URL = '/api/users/available-groups/'


class ProfileAndGroupsScopingTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='owner',
            email='owner@example.com',
            password='pass12345',
        )
        self.other = User.objects.create_user(
            username='stranger',
            email='stranger@example.com',
            password='pass12345',
        )
        self.own_group = Group.objects.create(name='own-group')
        self.other_group = Group.objects.create(name='other-group')
        self.user.groups.add(self.own_group)
        self.other.groups.add(self.other_group)
        self.client.force_login(self.user)
        self.api_client = APIClient()
        self.api_client.force_authenticate(user=self.user)

    def test_update_user_view_does_not_expose_foreign_profile(self) -> None:
        response = self.client.get(
            reverse('users:update_user', kwargs={'pk': self.other.pk}),
        )
        self.assertNotContains(response, self.other.email)

    def test_groups_api_ignores_foreign_user_id(self) -> None:
        response = self.api_client.get(GROUPS_URL, {'user_id': self.other.pk})
        self.assertEqual(response.status_code, 200)
        names = [g['name'] for g in response.json()['groups']]
        self.assertEqual(names, ['own-group'])

    def test_available_groups_api_does_not_list_foreign_groups(self) -> None:
        response = self.api_client.get(
            AVAILABLE_GROUPS_URL,
            {'user_id': self.other.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['groups'], [])
