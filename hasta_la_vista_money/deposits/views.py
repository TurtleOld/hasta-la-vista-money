from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, ListView, TemplateView

from hasta_la_vista_money.deposits.commands import (
    FundDepositCommand,
    OpenExistingDepositCommand,
)
from hasta_la_vista_money.deposits.forms import CreateDepositForm
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
        context['deposit'] = get_object_or_404(
            service.get_user_deposits(user),
            pk=self.kwargs['pk'],
        )
        return context

    def get_success_url(self) -> str:
        return reverse('deposits:list')
