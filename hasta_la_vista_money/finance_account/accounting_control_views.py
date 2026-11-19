"""Unified accounting control page: one list of unresolved problems."""

from datetime import date
from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

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


def _selected(request: HttpRequest) -> dict[str, str]:
    return {
        'account': request.GET.get('account', ''),
        'bank': request.GET.get('bank', ''),
        'currency': request.GET.get('currency', ''),
        'kind': request.GET.get('kind', ''),
        'state': request.GET.get('state', ProblemState.ALL),
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
    }


def _valid_kind(value: str) -> str:
    return value if value in set(ProblemKind) else ''


def _valid_state(value: str) -> str:
    return value if value in set(ProblemState) else ProblemState.ALL


# PostgreSQL bigint / Django BigAutoField upper bound.
_MAX_BIGAUTO_ID = 2**63 - 1


def _account_id_or_none(value: str) -> tuple[int | None, bool]:
    """Parse an account id, rejecting non-ASCII digits and overflow.

    Returns ``(id, invalid)``. A missing value is not an error; malformed
    input is reported to the existing filter-error path instead of raising.
    """
    if not value:
        return None, False
    if not value.isascii() or not value.isdigit():
        return None, True
    normalized = value.lstrip('0') or '0'
    if len(normalized) > len(str(_MAX_BIGAUTO_ID)):
        return None, True
    candidate = int(normalized)
    if candidate < 1 or candidate > _MAX_BIGAUTO_ID:
        return None, True
    return candidate, False


def _date_or_none(value: str) -> tuple[date | None, bool]:
    """Parse an optional filter date without letting invalid input raise."""
    if not value:
        return None, False
    try:
        parsed = parse_date(value)
    except (TypeError, ValueError):
        return None, True
    if parsed is None:
        return None, True
    return parsed, False


class AccountingControlView(LoginRequiredMixin, TemplateView):
    """Show every bank statement problem of the owner in one place."""

    template_name = 'finance_account/accounting_control.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = cast('User', self.request.user)
        service = _problem_service(self.request)
        selected = _selected(self.request)
        selected['kind'] = _valid_kind(selected['kind'])
        selected['state'] = _valid_state(selected['state'])
        account_id, account_invalid = _account_id_or_none(
            selected['account'],
        )
        start, start_invalid = _date_or_none(selected['date_from'])
        end, end_invalid = _date_or_none(selected['date_to'])
        account_ids = (account_id,) if account_id is not None else ()
        errors: list[str] = []
        if account_invalid:
            errors.append(str(_('Некорректное значение счёта в фильтре.')))
            selected['account'] = ''
        if start_invalid:
            errors.append(str(_('Некорректная дата начала в фильтре.')))
            selected['date_from'] = ''
        if end_invalid:
            errors.append(str(_('Некорректная дата конца в фильтре.')))
            selected['date_to'] = ''
        filters = AccountingProblemFilter(
            bank_code=selected['bank'],
            currency=selected['currency'],
            kind=selected['kind'],
            state=selected['state'],
        )
        error = ' '.join(errors)
        try:
            problem_list = service.problems(
                user,
                account_ids=account_ids,
                start=start,
                end=end,
                filters=filters,
            )
        except ValidationError as exc:
            error = ' '.join(filter(None, (error, ' '.join(exc.messages))))
            selected['account'] = ''
            problem_list = service.problems(
                user,
                filters=AccountingProblemFilter(
                    bank_code=selected['bank'],
                    currency=selected['currency'],
                    kind=selected['kind'],
                    state=selected['state'],
                ),
            )
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
