from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.middleware import AuditOperationMiddleware
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.system.services.audit_context import (
    current_operation_id,
)
from hasta_la_vista_money.users.models import User

ACCOUNT_LABEL = 'finance_account.Account'


class AuditOperationMiddlewareTests(TestCase):
    """The middleware is a safety net for saves outside the service layer."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='middleware-user')
        self.factory = RequestFactory()

    def test_request_gives_a_default_operation_id_to_bare_saves(
        self,
    ) -> None:
        created: dict[str, Account] = {}

        def get_response(request: object) -> HttpResponse:
            del request
            created['account'] = Account.objects.create(user=self.user)
            return HttpResponse()

        middleware = AuditOperationMiddleware(get_response)
        middleware(self.factory.get('/'))

        log = AuditLog.objects.get(
            model_name=ACCOUNT_LABEL,
            object_pk=str(created['account'].pk),
        )
        self.assertIsNotNone(log.operation_id)
        self.assertIsNone(log.kind)

    def test_context_is_cleared_once_the_request_finishes(self) -> None:
        middleware = AuditOperationMiddleware(lambda _request: HttpResponse())
        middleware(self.factory.get('/'))
        self.assertIsNone(current_operation_id())
