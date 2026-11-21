"""Defer, exclude and resume actions for one bank statement row."""

from typing import TYPE_CHECKING, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views import View

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.forms import StatementRowExcludeForm
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.protocols.services import (
    StatementRowLinkServiceProtocol,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    ReconciliationDecisionConflictError,
    ReconciliationExpiredError,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer

#: HTTP status of each decision conflict a concurrent change can raise.
_DECISION_STATUS = {
    ReconciliationExpiredError: constants.GONE,
    ReconciliationDecisionConflictError: constants.CONFLICT,
}


def _decision_error_response(error: Exception) -> HttpResponse:
    """Map a decision conflict to its status, one place for every action."""
    for error_type, status in _DECISION_STATUS.items():
        if isinstance(error, error_type):
            return HttpResponse(status=status)
    raise error


def _link_service(
    request: HttpRequest,
) -> StatementRowLinkServiceProtocol:
    request_with_container = cast('RequestWithContainer', request)
    return cast(
        'StatementRowLinkServiceProtocol',
        request_with_container.container.users.statement_row_link_service(),
    )


def _owned_upload_row(
    request: HttpRequest,
    upload_id: int,
    row_id: int,
) -> BankStatementRow:
    """Return an owner's row, or 404 for another user's statement."""
    user = cast('User', request.user)
    get_object_or_404(
        BankStatementUpload,
        pk=upload_id,
        user=user,
        account__user=user,
    )
    return get_object_or_404(
        BankStatementRow,
        pk=row_id,
        upload_id=upload_id,
    )


def _decision_redirect(
    request: HttpRequest,
    upload_id: int,
) -> HttpResponse:
    """Return to the page that submitted the decision, if it is our own."""
    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(
        'finance_account:bank_statement_reconciliation',
        upload_id,
    )


class StatementRowDeferView(LoginRequiredMixin, View):
    """Leave a statement row unresolved for later."""

    http_method_names = ['post']

    def post(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        row = _owned_upload_row(request, upload_id, row_id)
        try:
            _link_service(request).defer(
                row.pk,
                cast('User', request.user).pk,
            )
        except (
            ReconciliationExpiredError,
            ReconciliationDecisionConflictError,
        ) as error:
            return _decision_error_response(error)
        messages.success(request, _('Строка отложена.'))
        return _decision_redirect(request, upload_id)


class StatementRowExcludeView(LoginRequiredMixin, View):
    """Consciously leave a statement row out, with a reason."""

    http_method_names = ['post']

    def post(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        row = _owned_upload_row(request, upload_id, row_id)
        reason = request.POST.get(f'reason-{row_id}', '') or request.POST.get(
            'reason',
            '',
        )
        form = StatementRowExcludeForm({'reason': reason})
        if not form.is_valid():
            messages.error(request, _('Укажите причину исключения строки.'))
            return _decision_redirect(request, upload_id)
        try:
            _link_service(request).exclude(
                row.pk,
                cast('User', request.user).pk,
                form.cleaned_data['reason'],
            )
        except ValidationError:
            messages.error(request, _('Укажите причину исключения строки.'))
            return _decision_redirect(request, upload_id)
        except (
            ReconciliationExpiredError,
            ReconciliationDecisionConflictError,
        ) as error:
            return _decision_error_response(error)
        messages.success(request, _('Строка исключена из учёта.'))
        return _decision_redirect(request, upload_id)


class StatementRowResumeView(LoginRequiredMixin, View):
    """Return a deferred or excluded row to its processing mechanism."""

    http_method_names = ['post']

    def post(
        self,
        request: HttpRequest,
        upload_id: int,
        row_id: int,
    ) -> HttpResponse:
        row = _owned_upload_row(request, upload_id, row_id)
        try:
            _link_service(request).resume(
                row.pk,
                cast('User', request.user).pk,
            )
        except (
            ReconciliationExpiredError,
            ReconciliationDecisionConflictError,
        ) as error:
            return _decision_error_response(error)
        messages.success(request, _('Строка возвращена на обработку.'))
        return _decision_redirect(request, upload_id)
