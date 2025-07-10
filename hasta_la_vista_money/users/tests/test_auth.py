from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.auth.forms import AuthenticationForm
from hasta_la_vista_money.users.services.auth import login_user

User = get_user_model()


class LoginUserServiceTest(TestCase):
    """Tests for login_user service function."""

    fixtures = ['users.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.first()
        self.user.set_password('testpassword')
        self.user.save()

    def get_request(self):
        request = self.factory.post('/login/')
        setattr(request, 'session', self.client.session)
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        return request

    def test_login_user_success(self):
        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': self.user.username,
                'password': 'testpassword',
            },
        )
        form.is_valid()  # populates cleaned_data
        result = login_user(request, form, 'Success!')
        self.assertTrue(result['success'])
        self.assertIn('access', result)
        self.assertIn('refresh', result)
        self.assertEqual(result['user'], self.user)

    def test_login_user_failure(self):
        request = self.get_request()
        form = AuthenticationForm(
            request,
            data={
                'username': self.user.username,
                'password': 'wrongpassword',
            },
        )
        form.is_valid()
        result = login_user(request, form, 'Fail!')
        self.assertFalse(result['success'])
