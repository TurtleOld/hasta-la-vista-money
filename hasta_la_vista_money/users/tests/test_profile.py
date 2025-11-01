from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth import get_user_model
from django.test import TestCase

from hasta_la_vista_money.users.forms import UpdateUserForm
from hasta_la_vista_money.users.services.profile import update_user_profile

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class UpdateUserProfileServiceTest(TestCase):
    """Tests for update_user_profile service function."""

    fixtures: ClassVar[list[str]] = ['users.yaml']  # type: ignore[misc]

    def setUp(self) -> None:
        user: UserType | None = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.user: UserType = user

    def test_update_user_profile(self) -> None:
        form: UpdateUserForm = UpdateUserForm(
            instance=self.user,
            data={
                'username': self.user.username,
                'email': 'newemail@example.com',
                'first_name': 'NewName',
                'last_name': self.user.last_name,
            },
        )
        self.assertTrue(form.is_valid())
        user: UserType = update_user_profile(form)
        self.assertEqual(user.email, 'newemail@example.com')
        self.assertEqual(user.first_name, 'NewName')
