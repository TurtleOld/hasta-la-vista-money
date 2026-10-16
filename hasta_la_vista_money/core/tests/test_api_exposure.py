from django.test import TestCase
from django.urls import Resolver404, resolve, reverse

from hasta_la_vista_money.users.models import User


class ApiSchemaAccessTest(TestCase):
    def test_schema_and_swagger_require_authentication(self) -> None:
        for name in ('schema', 'swagger-ui'):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertIn(response.status_code, (401, 403))

    def test_schema_available_to_authenticated_user(self) -> None:
        user = User.objects.create_user(username='schema-user', password='x')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('schema')).status_code, 200)


class DebugToolbarRouteTest(TestCase):
    def test_debug_toolbar_not_routed_when_debug_is_off(self) -> None:
        with self.assertRaises(Resolver404):
            resolve('/__debug__/render_panel/')
