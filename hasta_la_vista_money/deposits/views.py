from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from hasta_la_vista_money.deposits.commands import (
    AddFloatingRatePeriodCommand,
    ForecastTerms,
    FundDepositCommand,
    OpenExistingDepositCommand,
    RecalculateInterestForecastCommand,
    TopUpDepositCommand,
    TopUpTerms,
    WithdrawalTerms,
    WithdrawDepositCommand,
)
from hasta_la_vista_money.deposits.forms import (
    AddFloatingRatePeriodForm,
    CreateDepositForm,
    TopUpDepositForm,
    WithdrawDepositForm,
)
from hasta_la_vista_money.deposits.models import Deposit, DepositPrincipalEvent

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.users.models import User


class DepositListView(LoginRequiredMixin, ListView[Deposit]):
    template_name = 'deposits/deposit_list.html'
    context_object_name = 'deposits'

    def get_queryset(self) -> Any:
        user = cast('User', self.request.user)
        request = cast('Any', self.request)
        service = request.container.deposits.deposit_service()
        return service.get_user_deposits(user)


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
        forecast_terms = ForecastTerms(
            day_count_convention=data['day_count_convention'],
            accrual_start_included=data['accrual_start_included'],
            accrual_end_included=data['accrual_end_included'],
            payout_schedule_kind=data['payout_schedule_kind'],
            custom_payout_dates=data['custom_payout_dates'],
            business_day_convention=data['business_day_convention'],
        )
        withdrawal_terms = WithdrawalTerms(
            withdrawal_allowed=data['withdrawal_allowed'],
            minimum_withdrawal_amount=data['minimum_withdrawal_amount'],
            maximum_withdrawal_amount=data['maximum_withdrawal_amount'],
            withdrawal_deadline=data['withdrawal_deadline'],
            minimum_balance=data['minimum_balance'] or Decimal(),
        )
        top_up_terms = TopUpTerms(
            top_up_allowed=data['top_up_allowed'],
            minimum_top_up_amount=data['minimum_top_up_amount'],
            maximum_top_up_amount=data['maximum_top_up_amount'],
            top_up_deadline=data['top_up_deadline'],
            maximum_balance=data['maximum_balance'],
        )
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
        context['forecast_lines'] = (
            deposit.current_term.interest_forecasts.all()
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
        return context

    def get_success_url(self) -> str:
        return reverse('deposits:list')


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
