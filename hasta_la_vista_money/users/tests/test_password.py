from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.messages.storage.fallback import FallbackStorage
from hasta_la_vista_money.users.services.password import set_user_password

User = get_user_model()


class SetUserPasswordServiceTest(TestCase):
    """Tests for set_user_password service function."""

    fixtures = ['users.yaml']

    def setUp(self):
        self.user = User.objects.first()
        self.factory = RequestFactory()

    def get_request(self):
        request = self.factory.post('/set-password/')
        setattr(request, 'session', self.client.session)
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        return request

    def test_set_user_password(self):
        request = self.get_request()
        request.user = self.user
        form = SetPasswordForm(
            user=self.user,
            data={
                'new_password1': 'newsecurepassword',
                'new_password2': 'newsecurepassword',
            },
        )
        self.assertTrue(form.is_valid())
        set_user_password(form, request)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newsecurepassword'))
