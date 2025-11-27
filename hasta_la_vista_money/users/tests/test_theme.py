from typing import TYPE_CHECKING, ClassVar, cast

from django.contrib.auth import get_user_model
from django.test import TestCase

from hasta_la_vista_money.users.services.theme import set_user_theme

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class SetUserThemeServiceTest(TestCase):
    """Tests for set_user_theme service function."""

    fixtures: ClassVar[list[str]] = ['users.yaml']  # type: ignore[misc]

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: User = cast('User', user)

    def test_set_user_theme_light(self) -> None:
        result: bool = set_user_theme(self.user, 'light')  # type: ignore[arg-type]
        self.user.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(self.user.theme, 'light')  # type: ignore[attr-defined]

    def test_set_user_theme_dark(self) -> None:
        result: bool = set_user_theme(self.user, 'dark')  # type: ignore[arg-type]
        self.user.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(self.user.theme, 'dark')  # type: ignore[attr-defined]

    def test_set_user_theme_invalid(self) -> None:
        result: bool = set_user_theme(self.user, 'invalid_theme')  # type: ignore[arg-type]
        self.user.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(self.user.theme, 'light')  # type: ignore[attr-defined]
