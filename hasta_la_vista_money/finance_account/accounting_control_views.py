"""Unified accounting control page: one list of unresolved problems."""

from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from hasta_la_vista_money.finance_account.accounting_control_forms import (
    AccountingControlFilterForm,
)
from hasta_la_vista_money.users.accounting_types import (
    AccountingProblemFilter,
    ProblemKind,
    ProblemState,
)
from hasta_la_vista_money.users.protocols.services import (
    AccountingProblemServiceProtocol,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.users.models import User

KIND_LABELS: dict[str, Any] = {
    ProblemKind.DEFERRED: _('Отложена'),
    ProblemKind.INCOMPLETE_MARKUP: _('Ждёт разметки'),
    ProblemKind.UNRESOLVED: _('Ожидает решения'),
    ProblemKind.PROBABLE_DUPLICATE: _('Вероятный дубль'),
    ProblemKind.REPAYMENT: _('Погашение без перевода'),
    ProblemKind.PARSE_ERROR: _('Ошибка разбора'),
    ProblemKind.UPLOAD_FAILED: _('Ошибка загрузки'),
    ProblemKind.RECOVERY: _('Нужна повторная загрузка'),
    ProblemKind.BALANCE_ATTENTION: _('Проверить остаток'),
}
STATE_LABELS: dict[str, Any] = {
    ProblemState.ALL: _('Все'),
    ProblemState.AVAILABLE: _('Данные доступны'),
    ProblemState.RECOVERY: _('Только восстановление'),
}


def _problem_service(
    request: HttpRequest,
) -> AccountingProblemServiceProtocol:
    request_with_container = cast('RequestWithContainer', request)
    return cast(
        'AccountingProblemServiceProtocol',
        request_with_container.container.users.accounting_problem_service(),
    )


def _selected(data: dict[str, Any]) -> dict[str, str]:
    account = data.get('account')
    start = data.get('date_from')
    end = data.get('date_to')
    return {
        'account': str(account) if account is not None else '',
        'bank': data.get('bank') or '',
        'currency': data.get('currency') or '',
        'kind': data.get('kind') or '',
        'state': data.get('state') or ProblemState.ALL,
        'date_from': start.isoformat() if start is not None else '',
        'date_to': end.isoformat() if end is not None else '',
    }


class AccountingControlView(LoginRequiredMixin, TemplateView):
    """Show every bank statement problem of the owner in one place."""

    template_name = 'finance_account/accounting_control.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = cast('User', self.request.user)
        service = _problem_service(self.request)
        form = AccountingControlFilterForm(self.request.GET)
        is_valid = form.is_valid()
        data = form.cleaned_data if is_valid else {}
        selected = _selected(data)
        filters = AccountingProblemFilter(
            bank_code=selected['bank'],
            currency=selected['currency'],
            kind=selected['kind'],
            state=selected['state'],
        )
        account_id = data.get('account')
        account_ids = (account_id,) if account_id is not None else ()
        error = ' '.join(
            str(message)
            for messages in form.errors.values()
            for message in messages
        )
        try:
            problem_list = service.problems(
                user,
                account_ids=account_ids,
                start=data.get('date_from'),
                end=data.get('date_to'),
                filters=filters,
            )
        except ValidationError as exc:
            # The chosen account or period is not provable for this owner:
            # show the same list without them instead of failing the page.
            error = ' '.join(filter(None, (error, ' '.join(exc.messages))))
            selected['account'] = ''
            selected['date_from'] = ''
            selected['date_to'] = ''
            problem_list = service.problems(user, filters=filters)
        context.update(
            {
                'problem_list': problem_list,
                'selected': selected,
                'filter_error': error,
                'kind_labels': KIND_LABELS,
                'state_labels': STATE_LABELS,
                'banks': sorted(
                    {
                        (account.bank_code, account.bank_name)
                        for account in problem_list.accounts
                    },
                ),
                'currencies': sorted(
                    {account.currency for account in problem_list.accounts},
                ),
            },
        )
        return context
