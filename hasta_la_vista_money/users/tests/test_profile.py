from django.test import TestCase
from django.contrib.auth import get_user_model
from hasta_la_vista_money.users.services.profile import update_user_profile
from hasta_la_vista_money.users.forms import UpdateUserForm

User = get_user_model()


class UpdateUserProfileServiceTest(TestCase):
    """Tests for update_user_profile service function."""

    fixtures = ['users.yaml']

    def setUp(self):
        self.user = User.objects.first()

    def test_update_user_profile(self):
        form = UpdateUserForm(
            instance=self.user,
            data={
                'username': self.user.username,
                'email': 'newemail@example.com',
                'first_name': 'NewName',
                'last_name': self.user.last_name,
            },
        )
        self.assertTrue(form.is_valid())
        user = update_user_profile(form)
        self.assertEqual(user.email, 'newemail@example.com')
        self.assertEqual(user.first_name, 'NewName')
