from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from hasta_la_vista_money.deposits.commands import (
    AddFloatingRatePeriodCommand,
    CapitalizeInterestCommand,
    CloseDepositEarlyCommand,
    CloseMaturedDepositCommand,
    EarlyClosureTerms,
    ForecastEarlyClosureCommand,
    ForecastTerms,
    FundDepositCommand,
    OpenExistingDepositCommand,
    RecalculateInterestForecastCommand,
    RenewDepositCommand,
    ReverseDepositEventCommand,
    TopUpDepositCommand,
    TopUpTerms,
    WithdrawalTerms,
    WithdrawDepositCommand,
)
from hasta_la_vista_money.deposits.forms import (
    AddFloatingRatePeriodForm,
    CapitalizeInterestForm,
    CloseDepositEarlyForm,
    CloseMaturedDepositForm,
    CreateDepositForm,
    ForecastEarlyClosureForm,
    RenewDepositForm,
    ReverseDepositEventForm,
    TopUpDepositForm,
    WithdrawDepositForm,
)
from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositCapitalizationEvent,
    DepositPrincipalEvent,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.users.models import User


def _contract_terms_from_data(
    data: dict[str, Any],
) -> tuple[
    ForecastTerms,
    WithdrawalTerms,
    TopUpTerms,
    EarlyClosureTerms,
]:
    return (
        ForecastTerms(
            day_count_convention=data['day_count_convention'],
            accrual_start_included=data['accrual_start_included'],
            accrual_end_included=data['accrual_end_included'],
            payout_schedule_kind=data['payout_schedule_kind'],
            custom_payout_dates=data['custom_payout_dates'],
            business_day_convention=data['business_day_convention'],
            interest_payout_destination=data['interest_payout_destination'],
        ),
        WithdrawalTerms(
            withdrawal_allowed=data['withdrawal_allowed'],
            minimum_withdrawal_amount=data['minimum_withdrawal_amount'],
            maximum_withdrawal_amount=data['maximum_withdrawal_amount'],
            withdrawal_deadline=data['withdrawal_deadline'],
            minimum_balance=data['minimum_balance'] or Decimal(),
        ),
        TopUpTerms(
            top_up_allowed=data['top_up_allowed'],
            minimum_top_up_amount=data['minimum_top_up_amount'],
            maximum_top_up_amount=data['maximum_top_up_amount'],
            top_up_deadline=data['top_up_deadline'],
            maximum_balance=data['maximum_balance'],
        ),
        EarlyClosureTerms(
            annual_rate=data['early_closure_annual_rate'],
            recalculation_scope=data['early_closure_recalculation_scope'],
            withdrawn_amount=data['early_closure_withdrawn_amount'],
        ),
    )


class DepositListView(LoginRequiredMixin, ListView[Deposit]):
    template_name = 'deposits/deposit_list.html'
    context_object_name = 'deposits'

    def get_queryset(self) -> Any:
        user = cast('User', self.request.user)
        request = cast('Any', self.request)
        service = request.container.deposits.deposit_service()
        overview = service.get_user_deposit_overview(user)
        self.active_deposits = overview.active_deposits
        self.archived_deposits = overview.archived_deposits
        self.overview_by_currency = overview.by_currency
        return (*overview.active_deposits, *overview.archived_deposits)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(
            active_deposits=self.active_deposits,
            archived_deposits=self.archived_deposits,
            overview_by_currency=self.overview_by_currency,
        )
        return context


class DepositCreateView(LoginRequiredMixin, FormView[CreateDepositForm]):
    form_class = CreateDepositForm
    template_name = 'deposits/deposit_form.html'

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['user'] = cast('User', self.request.user)
        return kwargs

    def form_valid(self, form: CreateDepositForm) -> HttpResponse:
        user = cast('User', self.request.user)
        data = form.cleaned_data
        request = cast('Any', self.request)
        service = request.container.deposits.deposit_service()
        (
            forecast_terms,
            withdrawal_terms,
            top_up_terms,
            early_closure_terms,
        ) = _contract_terms_from_data(data)
        try:
            if data['opening_method'] == DepositPrincipalEvent.Type.FUNDING:
                source_account = cast('Account', data['source_account'])
                deposit = service.create_funded_term_deposit(
                    FundDepositCommand(
                        user=user,
                        name=data['name'],
                        bank=data['bank'],
                        currency=data['currency'],
                        amount=data['balance'],
                        source_account_id=source_account.pk,
                        opened_on=data['opened_on'],
                        matures_on=data['matures_on'],
                        annual_rate=data['annual_rate'],
                        rate_kind=data['rate_kind'],
                        forecast_terms=forecast_terms,
                        withdrawal_terms=withdrawal_terms,
                        top_up_terms=top_up_terms,
                        early_closure_terms=early_closure_terms,
                    ),
                )
            else:
                deposit = service.open_existing_term_deposit(
                    OpenExistingDepositCommand(
                        user=user,
                        name=data['name'],
                        bank=data['bank'],
                        currency=data['currency'],
                        current_balance=data['balance'],
                        tracking_started_on=data['tracking_started_on'],
                        opened_on=data['opened_on'],
                        matures_on=data['matures_on'],
                        annual_rate=data['annual_rate'],
                        rate_kind=data['rate_kind'],
                        forecast_terms=forecast_terms,
                        withdrawal_terms=withdrawal_terms,
                        top_up_terms=top_up_terms,
                        early_closure_terms=early_closure_terms,
                    ),
                )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, _('Срочный вклад успешно создан.'))
        return HttpResponseRedirect(deposit.get_absolute_url())


class DepositDetailView(LoginRequiredMixin, TemplateView):
    template_name = 'deposits/deposit_detail.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = cast('User', self.request.user)
        request = cast('Any', self.request)
        service = request.container.deposits.deposit_service()
        deposit = get_object_or_404(
            service.get_user_deposits(user),
            pk=self.kwargs['pk'],
        )
        context['deposit'] = deposit
        context['renewal_available'] = service.is_renewal_available(deposit)
        context['forecast_lines'] = (
            deposit.current_term.interest_forecasts.all()
        )
        context['capitalization_events'] = (
            deposit.capitalization_events.select_related(
                'destination_account',
                'reversal_of',
            )
        )
        context['principal_events'] = deposit.principal_events.select_related(
            'source_account',
            'destination_account',
            'reversal_of',
        )
        context['renewal_events'] = deposit.renewal_events.select_related(
            'previous_term',
            'renewed_term',
            'reversal_of',
        )
        context['reverse_form'] = ReverseDepositEventForm(
            initial={'reversed_on': timezone.localdate()},
        )
        context['closure_event'] = (
            deposit.principal_events.filter(
                type__in=(
                    DepositPrincipalEvent.Type.PLANNED_CLOSURE,
                    DepositPrincipalEvent.Type.EARLY_CLOSURE,
                ),
            )
            .select_related('destination_account')
            .first()
        )
        context['capitalize_form'] = CapitalizeInterestForm(
            term=deposit.current_term,
            user=user,
        )
        context['withdraw_form'] = WithdrawDepositForm(
            user=user,
            currency=deposit.account.currency,
            initial={'effective_on': deposit.current_term.opened_on},
        )
        context['top_up_form'] = TopUpDepositForm(
            user=user,
            currency=deposit.account.currency,
            initial={'effective_on': deposit.current_term.opened_on},
        )
        context['close_form'] = CloseMaturedDepositForm(
            term=deposit.current_term,
            user=user,
        )
        context['early_closure_forecast_form'] = ForecastEarlyClosureForm(
            term=deposit.current_term,
        )
        context['audit_events'] = deposit.audit_events.all()[:20]
        context['reconciliation'] = self._compute_reconciliation(deposit)
        return context

    @staticmethod
    def _compute_reconciliation(
        deposit: 'Deposit',
    ) -> dict[str, Any] | None:
        events = deposit.principal_events.all()
        calculated = Decimal()
        for event in events:
            is_outflow = event.type in (
                DepositPrincipalEvent.Type.WITHDRAWAL,
                DepositPrincipalEvent.Type.PLANNED_CLOSURE,
                DepositPrincipalEvent.Type.EARLY_CLOSURE,
            )
            amount = -event.amount if is_outflow else event.amount
            calculated += -amount if event.reversal_of_id else amount
        for cap_event in deposit.capitalization_events.filter(
            destination=(DepositCapitalizationEvent.Destination.CAPITALIZATION),
        ):
            net = cap_event.net
            calculated += -net if cap_event.reversal_of_id else net
        account = deposit.account
        return {
            'calculated_balance': calculated,
            'account_balance': account.balance,
            'discrepancy': account.balance - calculated,
            'last_reconciled_at': account.last_reconciled_at,
        }

    def get_success_url(self) -> str:
        return reverse('deposits:list')


class DepositEventReverseView(LoginRequiredMixin, View):
    def post(
        self,
        request: HttpRequest,
        pk: int,
        event_kind: str,
        event_id: int,
    ) -> HttpResponse:
        form = ReverseDepositEventForm(request.POST)
        if not form.is_valid():
            messages.error(request, _('Укажите причину и дату аннулирования.'))
            return HttpResponseRedirect(
                reverse('deposits:detail', kwargs={'pk': pk}),
            )
        typed_request = cast('Any', request)
        service = typed_request.container.deposits.deposit_service()
        try:
            event = service.reverse_deposit_event(
                ReverseDepositEventCommand(
                    user=cast('User', request.user),
                    deposit_id=pk,
                    event_kind=event_kind,
                    event_id=event_id,
                    reason=form.cleaned_data['reason'],
                    reversed_on=form.cleaned_data['reversed_on'],
                ),
            )
        except ValidationError as error:
            raise Http404 from error
        messages.success(request, _('Событие вклада аннулировано.'))
        return HttpResponseRedirect(event.deposit.get_absolute_url())


class DepositReconcileView(LoginRequiredMixin, View):
    def post(
        self,
        request: HttpRequest,
        pk: int,
    ) -> HttpResponse:
        user = cast('User', request.user)
        typed_request = cast('Any', request)
        service = typed_request.container.deposits.deposit_service()
        deposit = get_object_or_404(service.get_user_deposits(user), pk=pk)
        try:
            result = service.reconcile_deposit(deposit.pk, user)
        except ValidationError as error:
            messages.error(request, error.message)
            return HttpResponseRedirect(deposit.get_absolute_url())
        discrepancy = result['discrepancy']
        if discrepancy == 0:
            messages.success(request, _('Сверка выполнена. Расхождений нет.'))
        else:
            messages.warning(
                request,
                _(
                    'Сверка завершена. Обнаружено расхождение: {amount}.',
                ).format(amount=abs(discrepancy)),
            )
        return HttpResponseRedirect(deposit.get_absolute_url())


class DepositRenewView(LoginRequiredMixin, FormView[RenewDepositForm]):
    form_class = RenewDepositForm
    template_name = 'deposits/deposit_renew.html'

    def get_deposit(self) -> Deposit:
        user = cast('User', self.request.user)
        request = cast('Any', self.request)
        service = request.container.deposits.deposit_service()
        deposit = cast(
            'Deposit',
            get_object_or_404(
                service.get_user_deposits(user),
                pk=self.kwargs['pk'],
            ),
        )
        if not service.is_renewal_available(deposit):
            raise Http404
        return deposit

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['term'] = self.get_deposit().current_term
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['deposit'] = self.get_deposit()
        return context

    def form_valid(self, form: RenewDepositForm) -> HttpResponse:
        deposit = self.get_deposit()
        user = cast('User', self.request.user)
        data = form.cleaned_data
        (
            forecast_terms,
            withdrawal_terms,
            top_up_terms,
            early_closure_terms,
        ) = _contract_terms_from_data(data)
        request = cast('Any', self.request)
        service = request.container.deposits.deposit_service()
        try:
            service.renew_matured_deposit(
                RenewDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    opened_on=data['opened_on'],
                    matures_on=data['matures_on'],
                    annual_rate=data['annual_rate'],
                    rate_kind=data['rate_kind'],
                    forecast_terms=forecast_terms,
                    withdrawal_terms=withdrawal_terms,
                    top_up_terms=top_up_terms,
                    early_closure_terms=early_closure_terms,
                ),
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, _('Вклад успешно пролонгирован.'))
        return HttpResponseRedirect(deposit.get_absolute_url())


class DepositRecalculateForecastView(LoginRequiredMixin, View):
    def post(
        self,
        request: HttpRequest,
        pk: int,
        term_id: int,
    ) -> HttpResponse:
        user = cast('User', request.user)
        typed_request = cast('Any', request)
        service = typed_request.container.deposits.deposit_service()
        deposit = get_object_or_404(
            service.get_user_deposits(user),
            pk=pk,
        )
        try:
            service.recalculate_forecast(
                RecalculateInterestForecastCommand(
                    user=user,
                    term_id=term_id,
                ),
            )
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, _('Прогноз выплат пересчитан.'))
        return HttpResponseRedirect(deposit.get_absolute_url())


class DepositWithdrawView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = cast('User', request.user)
        typed_request = cast('Any', request)
        service = typed_request.container.deposits.deposit_service()
        deposit = get_object_or_404(service.get_user_deposits(user), pk=pk)
        form = WithdrawDepositForm(
            request.POST,
            user=user,
            currency=deposit.account.currency,
        )
        if not form.is_valid():
            messages.error(request, _('Проверьте данные снятия.'))
            return HttpResponseRedirect(deposit.get_absolute_url())
        destination = form.cleaned_data['destination_account']
        try:
            service.withdraw_deposit_principal(
                WithdrawDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    destination_account_id=destination.pk,
                    amount=form.cleaned_data['amount'],
                    effective_on=form.cleaned_data['effective_on'],
                    exception_reason=form.cleaned_data['exception_reason'],
                ),
            )
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, _('Тело вклада переведено на счёт.'))
        return HttpResponseRedirect(deposit.get_absolute_url())


class DepositTopUpView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = cast('User', request.user)
        typed_request = cast('Any', request)
        service = typed_request.container.deposits.deposit_service()
        deposit = get_object_or_404(service.get_user_deposits(user), pk=pk)
        form = TopUpDepositForm(
            request.POST,
            user=user,
            currency=deposit.account.currency,
        )
        if not form.is_valid():
            messages.error(request, _('Проверьте данные пополнения.'))
            return HttpResponseRedirect(deposit.get_absolute_url())
        source = form.cleaned_data['source_account']
        try:
            service.top_up_deposit_principal(
                TopUpDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    source_account_id=source.pk,
                    amount=form.cleaned_data['amount'],
                    effective_on=form.cleaned_data['effective_on'],
                    exception_reason=form.cleaned_data['exception_reason'],
                ),
            )
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, _('Тело вклада пополнено.'))
        return HttpResponseRedirect(deposit.get_absolute_url())


class DepositAddRatePeriodView(
    LoginRequiredMixin,
    FormView[AddFloatingRatePeriodForm],
):
    form_class = AddFloatingRatePeriodForm
    template_name = 'deposits/deposit_add_rate_period.html'

    def get_deposit(self) -> Deposit:
        user = cast('User', self.request.user)
        request = cast('Any', self.request)
        service = request.container.deposits.deposit_service()
        return cast(
            'Deposit',
            get_object_or_404(
                service.get_user_deposits(user),
                pk=self.kwargs['pk'],
            ),
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['deposit'] = self.get_deposit()
        return context

    def form_valid(self, form: AddFloatingRatePeriodForm) -> HttpResponse:
        deposit = self.get_deposit()
        user = cast('User', self.request.user)
        data = form.cleaned_data
        request = cast('Any', self.request)
        service = request.container.deposits.deposit_service()
        try:
            service.add_floating_rate_period(
                AddFloatingRatePeriodCommand(
                    user=user,
                    term_id=self.kwargs['term_id'],
                    starts_on=data['starts_on'],
                    annual_rate=data['annual_rate'],
                    note=data['note'],
                ),
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, _('Ставка вклада обновлена.'))
        return HttpResponseRedirect(deposit.get_absolute_url())


class DepositCapitalizeInterestView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = cast('User', request.user)
        typed_request = cast('Any', request)
        service = typed_request.container.deposits.deposit_service()
        deposit = get_object_or_404(service.get_user_deposits(user), pk=pk)
        term = deposit.current_term
        form = CapitalizeInterestForm(request.POST, term=term, user=user)
        if not form.is_valid():
            for field, errors in form.errors.items():
                label = (
                    form.fields[field].label if field in form.fields else None
                )
                for error in errors:
                    messages.error(
                        request,
                        f'{label}: {error}' if label else str(error),
                    )
            return HttpResponseRedirect(deposit.get_absolute_url())
        forecast = form.cleaned_data.get('forecast')
        try:
            service.confirm_interest_payment(
                CapitalizeInterestCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    forecast_id=forecast.pk if forecast else None,
                    gross=form.cleaned_data['gross'],
                    withholding=form.cleaned_data['withholding'],
                    net=form.cleaned_data['net'],
                    posting_on=form.cleaned_data['posting_on'],
                    value_on=form.cleaned_data['value_on'],
                    reason=form.cleaned_data['reason'],
                    destination=form.cleaned_data['destination'],
                    destination_account_id=(
                        form.cleaned_data['destination_account'].pk
                        if form.cleaned_data['destination_account']
                        else None
                    ),
                ),
            )
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(
                request,
                _('Фактическая выплата процентов подтверждена.'),
            )
        return HttpResponseRedirect(deposit.get_absolute_url())


class DepositCloseView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = cast('User', request.user)
        typed_request = cast('Any', request)
        service = typed_request.container.deposits.deposit_service()
        deposit = get_object_or_404(service.get_user_deposits(user), pk=pk)
        form = CloseMaturedDepositForm(
            request.POST,
            term=deposit.current_term,
            user=user,
        )
        if not form.is_valid():
            messages.error(request, _('Проверьте данные закрытия вклада.'))
            return HttpResponseRedirect(deposit.get_absolute_url())
        destination_account = form.cleaned_data['destination_account']
        forecast = form.cleaned_data['forecast']
        try:
            service.close_matured_deposit(
                CloseMaturedDepositCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    destination=form.cleaned_data['destination'],
                    destination_account_id=(
                        destination_account.pk if destination_account else None
                    ),
                    principal=form.cleaned_data['principal'],
                    gross=form.cleaned_data['gross'],
                    withholding=form.cleaned_data['withholding'],
                    net=form.cleaned_data['net'],
                    posting_on=form.cleaned_data['posting_on'],
                    value_on=form.cleaned_data['value_on'],
                    forecast_id=forecast.pk if forecast else None,
                ),
            )
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, _('Вклад закрыт в плановый срок.'))
        return HttpResponseRedirect(deposit.get_absolute_url())


class DepositEarlyClosureView(LoginRequiredMixin, TemplateView):
    template_name = 'deposits/deposit_early_closure.html'

    def get_deposit(self) -> Deposit:
        user = cast('User', self.request.user)
        request = cast('Any', self.request)
        service = request.container.deposits.deposit_service()
        deposit = cast(
            'Deposit',
            get_object_or_404(
                service.get_user_deposits(user),
                pk=self.kwargs['pk'],
            ),
        )
        if deposit.current_term.state != 'active':
            raise Http404
        return deposit

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['deposit'] = self.get_deposit()
        return context

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = cast('User', request.user)
        typed_request = cast('Any', request)
        service = typed_request.container.deposits.deposit_service()
        deposit = self.get_deposit()
        if 'estimate' in request.POST:
            forecast_form = ForecastEarlyClosureForm(
                request.POST,
                term=deposit.current_term,
            )
            if not forecast_form.is_valid():
                return self.render_to_response(
                    {
                        'deposit': deposit,
                        'forecast_form': forecast_form,
                    },
                )
            forecast = service.forecast_early_closure(
                ForecastEarlyClosureCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    closure_on=forecast_form.cleaned_data['closure_on'],
                ),
            )
            initial = {
                'principal': forecast.principal,
                'gross': forecast.gross or Decimal(),
                'withholding': Decimal(),
                'net': forecast.gross or Decimal(),
                'posting_on': forecast_form.cleaned_data['closure_on'],
                'value_on': forecast_form.cleaned_data['closure_on'],
            }
            return self.render_to_response(
                {
                    'deposit': deposit,
                    'forecast': forecast,
                    'forecast_form': forecast_form,
                    'confirmation_form': CloseDepositEarlyForm(
                        term=deposit.current_term,
                        user=user,
                        initial=initial,
                    ),
                },
            )
        form = CloseDepositEarlyForm(
            request.POST,
            term=deposit.current_term,
            user=user,
        )
        if not form.is_valid():
            return self.render_to_response(
                {'deposit': deposit, 'confirmation_form': form},
            )
        destination_account = form.cleaned_data['destination_account']
        try:
            service.close_deposit_early(
                CloseDepositEarlyCommand(
                    user=user,
                    deposit_id=deposit.pk,
                    destination=form.cleaned_data['destination'],
                    destination_account_id=(
                        destination_account.pk if destination_account else None
                    ),
                    principal=form.cleaned_data['principal'],
                    gross=form.cleaned_data['gross'],
                    withholding=form.cleaned_data['withholding'],
                    net=form.cleaned_data['net'],
                    prior_interest_adjustment=form.cleaned_data[
                        'prior_interest_adjustment'
                    ],
                    posting_on=form.cleaned_data['posting_on'],
                    value_on=form.cleaned_data['value_on'],
                    closure_reason=form.cleaned_data['closure_reason'],
                ),
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.render_to_response(
                {'deposit': deposit, 'confirmation_form': form},
            )
        messages.success(request, _('Вклад закрыт досрочно.'))
        return HttpResponseRedirect(deposit.get_absolute_url())
