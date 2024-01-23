from django.contrib.messages.views import SuccessMessageMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
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


class LoanView(CustomNoPermissionMixin, SuccessMessageMixin, ListView):
    model = Loan
    template_name = 'loan/loan.html'
    no_permission_url = reverse_lazy('login')

    def get_context_data(self, *args, **kwargs):
        user = get_object_or_404(User, username=self.request.user)
        if user:
            loan_form = LoanForm()
            payment_make_loan_form = PaymentMakeLoanForm(user=self.request.user)
            loan = user.loan_users.all()
            result_calculate = user.payment_schedule_users.select_related(
                'loan',
            ).all()
            payment_make_loan = user.payment_make_loan_users.all()

            context = super().get_context_data(**kwargs)
            context['loan_form'] = loan_form
            context['payment_make_loan_form'] = payment_make_loan_form
            context['loan'] = loan
            context['result_calculate'] = result_calculate
            context['payment_make_loan'] = payment_make_loan

            return context


class LoanCreateView(CustomNoPermissionMixin, SuccessMessageMixin, CreateView):
    template_name = 'loan/loan.html'
    model = Loan
    form_class = LoanForm
    success_url = reverse_lazy('loan:list')
    success_message = constants.SUCCESS_MESSAGE_LOAN_CREATE

    def post(self, request, *args, **kwargs):
        loan_form = LoanForm(
            request.POST,
            user=request.user,
        )

        if loan_form.is_valid():
            loan_form.save()
            type_loan = loan_form.cleaned_data.get('type_loan')
            date = loan_form.cleaned_data.get('date')
            loan_amount = loan_form.cleaned_data.get('loan_amount')
            annual_interest_rate = loan_form.cleaned_data.get(
                'annual_interest_rate',
            )
            period_loan = loan_form.cleaned_data.get('period_loan')

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

            response_data = {'success': True}
        else:
            response_data = {
                'success': False,
                'errors': loan_form.errors,
            }
        return JsonResponse(response_data)


class LoanDeleteView(CustomNoPermissionMixin, SuccessMessageMixin, DeleteView):
    template_name = 'loan/loan.html'
    model = Loan
    success_url = reverse_lazy('loan:list')
    success_message = constants.SUCCESS_MESSAGE_LOAN_DELETE

    def form_valid(self, form):
        loan = self.get_object()
        account = loan.account
        loan.delete()
        account.delete()
        return super().form_valid(form)


class PaymentMakeCreateView(CreateView):
    template_name = 'loan/loan.html'
    model = PaymentMakeLoan
    form_class = PaymentMakeLoanForm
    success_url = reverse_lazy('loan:list')

    def post(self, request, *args, **kwargs):
        payment_make_form = self.form_class(request.user, request.POST)
        return create_object_view(
            form=payment_make_form,
            model=self.model,
            request=request,
            message=constants.SUCCESS_MESSAGE_PAYMENT_MAKE,
        )
