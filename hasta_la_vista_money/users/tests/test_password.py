from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase

from hasta_la_vista_money.users.services.password import set_user_password

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


def _dummy_get_response(_request: HttpRequest) -> HttpResponse:
    return HttpResponse()


class SetUserPasswordServiceTest(TestCase):
    """Tests for set_user_password service function."""

    fixtures: ClassVar[list[str]] = ['users.yaml']  # type: ignore[misc]

    def setUp(self) -> None:
        user: UserType | None = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.user: UserType = user
        self.factory: RequestFactory = RequestFactory()

    def get_request(self) -> HttpRequest:
        request: HttpRequest = self.factory.post('/set-password/')
        SessionMiddleware(_dummy_get_response).process_request(request)
        request.session.save()
        MessageMiddleware(_dummy_get_response).process_request(request)
        return request

    def test_set_user_password(self) -> None:
        request: HttpRequest = self.get_request()
        request.user = self.user
        form: SetPasswordForm[UserType] = SetPasswordForm(
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
