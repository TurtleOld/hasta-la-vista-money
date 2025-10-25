from typing import ClassVar

from django.contrib.auth import get_user_model
from django.test import TestCase

from hasta_la_vista_money.users.services.theme import set_user_theme

User = get_user_model()


class SetUserThemeServiceTest(TestCase):
    """Tests for set_user_theme service function."""

    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self):
        self.user = User.objects.first()

    def test_set_user_theme_light(self):
        result = set_user_theme(self.user, 'light')
        self.user.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(self.user.theme, 'light')

    def test_set_user_theme_dark(self):
        result = set_user_theme(self.user, 'dark')
        self.user.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(self.user.theme, 'dark')

    def test_set_user_theme_invalid(self):
        result = set_user_theme(self.user, 'invalid_theme')
        self.user.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(self.user.theme, 'light')
