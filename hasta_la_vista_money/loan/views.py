import structlog
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.views import create_object_view
from hasta_la_vista_money.custom_mixin import CustomNoPermissionMixin
from hasta_la_vista_money.loan.forms import LoanForm, PaymentMakeLoanForm
from hasta_la_vista_money.loan.models import Loan, PaymentMakeLoan
from hasta_la_vista_money.loan.tasks import (
    calculate_annuity_loan,
    calculate_differentiated_loan,
)
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


class LoanView(CustomNoPermissionMixin, SuccessMessageMixin, ListView):
    model = Loan
    template_name = 'loan/loan_modern.html'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, *args, **kwargs):
        user = get_object_or_404(User, username=self.request.user)
        loan_form = LoanForm()
        payment_make_loan_form = PaymentMakeLoanForm(user=self.request.user)
        loan = user.loan_users.all()
        result_calculate = user.payment_schedule_users.select_related(
            'loan',
        ).all()
        payment_make_loan = user.payment_make_loan_users.all()

        # Автоматический расчёт общей суммы кредитов и переплаты
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


class LoanCreateView(CustomNoPermissionMixin, SuccessMessageMixin, CreateView):
    template_name = 'loan/add_loan_modern.html'
    model = Loan
    form_class = LoanForm
    success_url = reverse_lazy('loan:list')
    success_message = constants.SUCCESS_MESSAGE_LOAN_CREATE
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['loan_form'] = self.form_class
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        type_loan = form.cleaned_data.get('type_loan')
        date = form.cleaned_data.get('date')
        loan_amount = form.cleaned_data.get('loan_amount')
        annual_interest_rate = form.cleaned_data.get(
            'annual_interest_rate',
        )
        period_loan = form.cleaned_data.get('period_loan')
        form.save()
        loan = Loan.objects.filter(
            date=date,
            loan_amount=loan_amount,
        ).first()

        if type_loan == 'Annuity':
            calculate_annuity_loan(
                user_id=self.request.user.pk,
                loan_id=loan.pk,
                start_date=date,
                loan_amount=loan_amount,
                annual_interest_rate=annual_interest_rate,
                period_loan=period_loan,
            )
        elif type_loan == 'Differentiated':
            calculate_differentiated_loan(
                user_id=self.request.user.pk,
                loan_id=loan.pk,
                start_date=date,
                loan_amount=loan_amount,
                annual_interest_rate=annual_interest_rate,
                period_loan=period_loan,
            )
        return redirect(self.success_url)


class LoanDeleteView(CustomNoPermissionMixin, SuccessMessageMixin, DeleteView):
    template_name = 'loan/loan.html'
    model = Loan
    success_url = reverse_lazy('loan:list')
    success_message = constants.SUCCESS_MESSAGE_LOAN_DELETE
    no_permission_url = reverse_lazy('login')

    def form_valid(self, form):
        loan = self.get_object()
        account = loan.account
        loan.delete()
        try:
            account.delete()
        except ProtectedError:
            logger.error(f'Account {account.name_account} is protected')
        return super().form_valid(form)


class PaymentMakeCreateView(CustomNoPermissionMixin, CreateView):
    template_name = 'loan/loan.html'
    model = PaymentMakeLoan
    form_class = PaymentMakeLoanForm
    success_url = reverse_lazy('loan:list')
    no_permission_url = reverse_lazy('login')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def post(self, request, *args, **kwargs):
        payment_make_form = self.form_class(request.user, request.POST)
        result = create_object_view(
            form=payment_make_form,
            model=self.model,
            request=request,
            message=constants.SUCCESS_MESSAGE_PAYMENT_MAKE,
        )
        return JsonResponse(result)
