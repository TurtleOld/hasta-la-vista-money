"""The unified accounting control entry with account and period selection."""

from datetime import date
from typing import TYPE_CHECKING, Final, cast
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from hasta_la_vista_money.finance_account.forms import (
    BalanceExplanationForm,
    ManualCoverageForm,
)
from hasta_la_vista_money.finance_account.mixins import GroupAccountMixin
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import BankStatementUpload
from hasta_la_vista_money.users.protocols.services import (
    AccountingControlServiceProtocol,
    StatementBalanceVerificationServiceProtocol,
    StatementCoverageServiceProtocol,
)
from hasta_la_vista_money.users.services.groups import can_write

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer
    from hasta_la_vista_money.users.models import User

ACTION_COVERAGE: Final = 'coverage'
ACTION_EXPLAIN_BALANCE: Final = 'explain_balance'
ACTION_RECHECK_BALANCE: Final = 'recheck_balance'


def _parse_date(value: str | None, default: date) -> date:
    """Parse an ISO date, falling back to the default."""
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


def _parse_account_id(value: str | None) -> int | None:
    """Parse a numeric account id, rejecting malformed values."""
    if not value or not value.isdigit():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _accounting_control_service(
    request: HttpRequest,
) -> AccountingControlServiceProtocol:
    """Resolve accounting control through the request container."""
    request_with_container = cast('RequestWithContainer', request)
    return cast(
        'AccountingControlServiceProtocol',
        request_with_container.container.users.accounting_control_service(),
    )


def _coverage_service(
    request: HttpRequest,
) -> StatementCoverageServiceProtocol:
    """Resolve period coverage through the request container."""
    request_with_container = cast('RequestWithContainer', request)
    return cast(
        'StatementCoverageServiceProtocol',
        request_with_container.container.users.statement_coverage_service(),
    )


def _balance_service(
    request: HttpRequest,
) -> StatementBalanceVerificationServiceProtocol:
    """Resolve balance verification through the request container."""
    request_with_container = cast('RequestWithContainer', request)
    return cast(
        'StatementBalanceVerificationServiceProtocol',
        request_with_container.container.users.statement_balance_verification_service(),
    )


class AccountingControlView(
    LoginRequiredMixin,
    GroupAccountMixin,
    TemplateView,
):
    """Show five separate measurements for one account and period."""

    template_name = 'finance_account/accounting_control.html'

    def _period(self) -> tuple[date, date]:
        """Return the selected period, defaulting to the current month."""
        today = timezone.localdate()
        period_start = _parse_date(
            self.request.GET.get('period_start'),
            today.replace(day=1),
        )
        period_end = _parse_date(self.request.GET.get('period_end'), today)
        if period_end < period_start:
            return today.replace(day=1), today
        return period_start, period_end

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Build the control entry context."""
        context = super().get_context_data(**kwargs)
        user = cast('User', self.request.user)
        accounts = self.get_accounts(user)
        account_id = _parse_account_id(self.request.GET.get('account'))
        selected = (
            accounts.filter(pk=account_id).first()
            if account_id is not None
            else None
        )
        period_start, period_end = self._period()
        control = (
            _accounting_control_service(self.request).build(
                selected,
                period_start,
                period_end,
            )
            if selected is not None
            else None
        )
        writable = selected is not None and can_write(user, selected)
        context.update(
            {
                'accounts': accounts,
                'selected_account': selected,
                'period_start': period_start,
                'period_end': period_end,
                'control': control,
                'can_write': writable,
                'coverage_form': (
                    ManualCoverageForm(
                        initial={
                            'period_start': period_start,
                            'period_end': period_end,
                        },
                    )
                    if writable
                    else None
                ),
                'explanation_form': (
                    BalanceExplanationForm() if writable else None
                ),
                'explain_action': ACTION_EXPLAIN_BALANCE,
                'recheck_action': ACTION_RECHECK_BALANCE,
            },
        )
        return context

    def post(self, request: HttpRequest) -> HttpResponse:
        """Record a coverage confirmation, balance explanation or recheck."""
        user = cast('User', request.user)
        account_id = _parse_account_id(request.POST.get('account'))
        if account_id is None:
            raise Http404
        account = get_object_or_404(Account, pk=account_id, user=user)
        action = request.POST.get('action', ACTION_COVERAGE)
        start = _parse_date(
            request.POST.get('period_start'),
            timezone.localdate().replace(day=1),
        )
        end = _parse_date(
            request.POST.get('period_end'),
            timezone.localdate(),
        )
        if action in {ACTION_EXPLAIN_BALANCE, ACTION_RECHECK_BALANCE}:
            upload_id = request.POST.get('upload_id', '')
            if not upload_id.isdigit():
                raise Http404
            upload = get_object_or_404(
                BankStatementUpload,
                pk=int(upload_id),
                account=account,
            )
            service = _balance_service(request)
            try:
                if action == ACTION_EXPLAIN_BALANCE:
                    explanation_form = BalanceExplanationForm(request.POST)
                    if not explanation_form.is_valid():
                        raise ValidationError(
                            _('Выберите утверждённый код объяснения.'),
                        )
                    service.explain(
                        upload,
                        user,
                        explanation_form.cleaned_data['code'],
                    )
                    messages.success(
                        request,
                        _('Расхождение остатка объяснено.'),
                    )
                else:
                    if upload.retention_cleaned_at is not None:
                        raise ValidationError(
                            _(
                                'Банковские данные очищены: '
                                'проверка недоступна.',
                            ),
                        )
                    service.verify(upload)
                    messages.success(
                        request,
                        _('Проверка остатка пересчитана.'),
                    )
            except (PermissionDenied, ValidationError) as error:
                messages.error(
                    request,
                    str(error) or _('Не удалось изменить проверку остатка.'),
                )
        else:
            coverage_form = ManualCoverageForm(request.POST)
            if coverage_form.is_valid():
                start = coverage_form.cleaned_data['period_start']
                end = coverage_form.cleaned_data['period_end']
                _coverage_service(request).confirm_manual(
                    user,
                    account,
                    start,
                    end,
                )
                messages.success(request, _('Период покрытия подтверждён.'))
            else:
                messages.error(
                    request,
                    _('Не удалось подтвердить период: проверьте даты.'),
                )
        params = {
            'account': account.pk,
            'period_start': start.isoformat(),
            'period_end': end.isoformat(),
        }
        group_id = request.POST.get('group_id')
        if group_id:
            params['group_id'] = group_id
        query = urlencode(params)
        return redirect(
            f'{reverse("finance_account:accounting_control")}?{query}',
        )
