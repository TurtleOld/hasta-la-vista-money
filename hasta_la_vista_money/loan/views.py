from typing import Any

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView

from hasta_la_vista_money import constants
from hasta_la_vista_money.loan.forms import LoanForm, PaymentMakeLoanForm
from hasta_la_vista_money.loan.models import Loan, PaymentMakeLoan
from hasta_la_vista_money.loan.services.loan_calculation import (
    LoanCalculationService,
)
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


class LoanView(LoginRequiredMixin, SuccessMessageMixin[Any], ListView[Loan]):
    model = Loan
    template_name = 'loan/loan_modern.html'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        user = get_object_or_404(User, username=self.request.user)
        loan_form = LoanForm()
        payment_make_loan_form = PaymentMakeLoanForm(user=self.request.user)  # type: ignore[no-untyped-call]
        loan = user.loan_users.all()
        result_calculate = user.payment_schedule_users.select_related(
            'loan',
        ).all()
        payment_make_loan = user.payment_make_loan_users.all()

        total_loan_amount = sum(loan_item.loan_amount for loan_item in loan)
        total_overpayment = sum(
            float(loan_item.calculate_sum_monthly_payment) for loan_item in loan
        )

        context = super().get_context_data(**kwargs)
        context['loan_form'] = loan_form
        context['payment_make_loan_form'] = payment_make_loan_form
        context['loan'] = loan
        context['result_calculate'] = result_calculate
        context['payment_make_loan'] = payment_make_loan
        context['total_loan_amount'] = total_loan_amount
        context['total_overpayment'] = total_overpayment

        return context


class LoanCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin[LoanForm],
    CreateView[Loan, LoanForm],
):
    template_name = 'loan/add_loan_modern.html'
    model = Loan
    form_class = LoanForm
    success_url = reverse_lazy('loan:list')
    success_message = constants.SUCCESS_MESSAGE_LOAN_CREATE
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['loan_form'] = self.form_class
        return context

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form: LoanForm) -> Any:
        type_loan = form.cleaned_data.get('type_loan')
        date = form.cleaned_data.get('date')
        loan_amount = form.cleaned_data.get('loan_amount')
        annual_interest_rate = form.cleaned_data.get(
            'annual_interest_rate',
        )
        period_loan = form.cleaned_data.get('period_loan')

        if not all(
            [type_loan, date, loan_amount, annual_interest_rate, period_loan]
        ):
            form.add_error(None, 'Все поля должны быть заполнены')
            return self.form_invalid(form)

        if not isinstance(self.request.user, User):
            raise TypeError('User must be authenticated')

        form.save()
        loan = Loan.objects.filter(
            date=date,
            loan_amount=loan_amount,
        ).first()

        if loan is None:
            form.add_error(None, 'Не удалось найти созданный кредит')
            return self.form_invalid(form)

        LoanCalculationService.run(
            type_loan=str(type_loan),
            user_id=self.request.user.pk,
            loan=loan,
            start_date=date,
            loan_amount=float(loan_amount),
            annual_interest_rate=float(annual_interest_rate),
            period_loan=int(period_loan),
        )
        return redirect(self.success_url)


class LoanDeleteView(
    LoginRequiredMixin, SuccessMessageMixin[Any], DeleteView[Loan, Any]
):
    template_name = 'loan/loan.html'
    model = Loan
    success_url = reverse_lazy('loan:list')
    success_message = constants.SUCCESS_MESSAGE_LOAN_DELETE
    no_permission_url = reverse_lazy('login')

    def form_valid(self, form: Any) -> Any:
        loan = self.get_object()
        account = loan.account
        loan.delete()
        try:
            account.delete()
        except ProtectedError:
            logger.exception('Account %s is protected', account.name_account)
        return super().form_valid(form)


class PaymentMakeCreateView(
    LoginRequiredMixin, CreateView[PaymentMakeLoan, PaymentMakeLoanForm]
):
    template_name = 'loan/loan.html'
    model = PaymentMakeLoan
    form_class = PaymentMakeLoanForm
    success_url = reverse_lazy('loan:list')
    no_permission_url = reverse_lazy('login')

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def post(self, request: Any, *args: Any, **kwargs: Any) -> JsonResponse:
        form = self.get_form()
        if not form.is_valid():
            return JsonResponse({'success': False, 'errors': form.errors})

        form_instance = form.save(commit=False)
        cd = form.cleaned_data
        amount = cd.get('amount')
        account = cd.get('account')
        loan = cd.get('loan')

        if not all([amount, account, loan]):
            return JsonResponse(
                {
                    'success': False,
                    'errors': {'__all__': ['Все поля должны быть заполнены']},
                },
            )

        if account is None:
            return JsonResponse(
                {
                    'success': False,
                    'errors': {'__all__': ['Счёт не выбран']},
                },
            )

        if account.user == request.user:
            form_instance.user = request.user
            form_instance.account = account
            form_instance.loan = loan
            form_instance.save()
            messages.success(request, constants.SUCCESS_MESSAGE_PAYMENT_MAKE)
            return JsonResponse({'success': True})
        return JsonResponse(
            {
                'success': False,
                'errors': {
                    '__all__': [
                        'У вас нет прав для выполнения этого действия',
                    ],
                },
            },
        )
