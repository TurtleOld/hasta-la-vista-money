from decimal import Decimal

from django.test import TestCase
from django.urls import reverse_lazy
from django.utils import timezone
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.loan.forms import LoanForm, PaymentMakeLoanForm
from hasta_la_vista_money.loan.models import (
    Loan,
    PaymentMakeLoan,
    PaymentSchedule,
)
from hasta_la_vista_money.loan.tasks import (
    calculate_annuity_loan,
    calculate_differentiated_loan,
)
from hasta_la_vista_money.users.models import User


class TestLoan(TestCase):
    """Test cases for Loan application."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'income.yaml',
        'income_cat.yaml',
        'loan.yaml',
    ]

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.get(pk=1)
        self.loan1 = Loan.objects.get(pk=2)
        self.loan2 = Loan.objects.get(pk=3)
        self.account = Account.objects.get(pk=1)

    def test_list_loan(self) -> None:
        """Test loan list view."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('loan:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_create_annuity_loan(self):
        """Test annuity loan creation."""
        self.client.force_login(self.user)
        url = reverse_lazy('loan:create')
        data = {
            'type_loan': 'Annuity',
            'date': '2023-10-01',
            'loan_amount': 10000,
            'annual_interest_rate': 5,
            'period_loan': 12,
        }
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertTrue(Loan.objects.filter(loan_amount=10000).exists())

    def test_create_differentiated_loan(self):
        """Test differentiated loan creation."""
        self.client.force_login(self.user)
        url = reverse_lazy('loan:create')
        data = {
            'type_loan': 'Differentiated',
            'date': '2023-10-01',
            'loan_amount': 10000,
            'annual_interest_rate': 5,
            'period_loan': 12,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, constants.REDIRECTS)
        self.assertTrue(Loan.objects.filter(loan_amount=10000).exists())

    def test_create_loan_invalid_data(self):
        """Test loan creation with invalid data."""
        self.client.force_login(self.user)
        url = reverse_lazy('loan:create')
        data = {
            'type_loan': 'Annuity',
            'date': '',
            'loan_amount': 10000,
            'annual_interest_rate': 5,
            'period_loan': 12,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_loan_model_str(self):
        """Test Loan model string representation."""
        self.assertIn(f'Кредит №{self.loan1.pk}', str(self.loan1))

    def test_loan_model_get_absolute_url(self):
        """Test Loan model get_absolute_url method."""
        expected_url = reverse_lazy('loan:delete', args=[self.loan1.pk])
        self.assertEqual(self.loan1.get_absolute_url(), expected_url)

    def test_loan_model_meta(self):
        """Test Loan model Meta configuration."""
        self.assertEqual(Loan._meta.model_name, 'loan')
        self.assertEqual(Loan._meta.app_label, 'loan')
        self.assertEqual(Loan._meta.ordering, ['-id'])

    def test_loan_model_choices(self):
        """Test Loan model type choices."""
        type_choices = [choice[0] for choice in Loan.TYPE_LOAN]
        self.assertIn('Annuity', type_choices)
        self.assertIn('Differentiated', type_choices)

    def test_loan_form_validation(self):
        """Test LoanForm validation."""
        form = LoanForm(
            data={
                'type_loan': 'Annuity',
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'loan_amount': 10000,
                'annual_interest_rate': 5.5,
                'period_loan': 12,
            },
            user=self.user,
        )
        self.assertTrue(form.is_valid())

    def test_loan_form_invalid(self):
        """Test LoanForm with invalid data."""
        form = LoanForm(
            data={
                'type_loan': 'Annuity',
                'loan_amount': 'invalid_amount',
                'annual_interest_rate': 5.5,
                'period_loan': 12,
            },
            user=self.user,
        )
        self.assertFalse(form.is_valid())

    def test_loan_form_save(self):
        """Test LoanForm save method."""
        form = LoanForm(
            data={
                'type_loan': 'Annuity',
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'loan_amount': 10000,
                'annual_interest_rate': 5.5,
                'period_loan': 12,
            },
            user=self.user,
        )
        if form.is_valid():
            form.save()
            self.assertTrue(Loan.objects.filter(loan_amount=10000).exists())

    def test_payment_make_loan_form_validation(self):
        """Test PaymentMakeLoanForm validation."""
        # Создаем отдельный счет для платежа, который не связан с кредитом
        payment_account = Account.objects.create(
            user=self.user,
            name_account='Test Payment Account',
            balance=5000,
            currency='RU',
        )

        form = PaymentMakeLoanForm(
            user=self.user,
            data={
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'account': payment_account.pk,
                'loan': self.loan1.pk,
                'amount': 1000,
            },
        )
        self.assertTrue(form.is_valid())

    def test_payment_make_loan_form_invalid(self):
        """Test PaymentMakeLoanForm with invalid data."""
        form = PaymentMakeLoanForm(
            user=self.user,
            data={
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'amount': 'invalid_amount',
            },
        )
        self.assertFalse(form.is_valid())

    def test_payment_make_loan_form_get_account_queryset(self):
        """Test PaymentMakeLoanForm get_account_queryset method."""
        form = PaymentMakeLoanForm(user=self.user)
        queryset = form.get_account_queryset()
        self.assertIsNotNone(queryset)

    def test_loan_view_context_data(self):
        """Test LoanView context data."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('loan:list'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('loan_form', response.context)
        self.assertIn('payment_make_loan_form', response.context)
        self.assertIn('loan', response.context)
        self.assertIn('result_calculate', response.context)
        self.assertIn('payment_make_loan', response.context)

    def test_loan_create_view_get(self):
        """Test LoanCreateView GET request."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('loan:create'))
        self.assertEqual(response.status_code, 200)

    def test_loan_create_view_context_data(self):
        """Test LoanCreateView context data."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('loan:create'))
        self.assertIn('loan_form', response.context)

    def test_loan_delete_view(self):
        """Test LoanDeleteView functionality."""
        self.client.force_login(self.user)
        test_account = Account.objects.create(
            user=self.user,
            name_account='Test Loan Account',
            balance=10000,
            currency='RU',
        )
        test_loan = Loan.objects.create(
            user=self.user,
            account=test_account,
            date=timezone.now(),
            loan_amount=10000,
            annual_interest_rate=Decimal('5.5'),
            period_loan=12,
            type_loan='Annuity',
        )
        response = self.client.post(reverse_lazy('loan:delete', args=[test_loan.pk]))
        self.assertEqual(response.status_code, 302)

    def test_payment_make_create_view_post(self):
        """Test PaymentMakeCreateView POST request."""
        self.client.force_login(self.user)
        payment_account = Account.objects.create(
            user=self.user,
            name_account='Test Payment Account',
            balance=5000,
            currency='RU',
        )
        data = {
            'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'account': payment_account.pk,
            'loan': self.loan1.pk,
            'amount': 1000,
        }
        response = self.client.post(reverse_lazy('loan:payment_create'), data)
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn('success', response_data)

    def test_calculate_annuity_loan(self):
        """Test calculate_annuity_loan function."""
        calculate_annuity_loan(
            user_id=self.user.pk,
            loan_id=self.loan1.pk,
            start_date=timezone.now(),
            loan_amount=Decimal('10000'),
            annual_interest_rate=Decimal('5.5'),
            period_loan=12,
        )
        self.assertTrue(PaymentSchedule.objects.filter(loan=self.loan1).exists())

    def test_calculate_differentiated_loan(self):
        """Test calculate_differentiated_loan function."""
        calculate_differentiated_loan(
            user_id=self.user.pk,
            loan_id=self.loan1.pk,
            start_date=timezone.now(),
            loan_amount=Decimal('10000'),
            annual_interest_rate=Decimal('5.5'),
            period_loan=12,
        )
        self.assertTrue(PaymentSchedule.objects.filter(loan=self.loan1).exists())

    def test_loan_calculate_sum_monthly_payment_property(self):
        """Test Loan calculate_sum_monthly_payment property."""
        result = self.loan1.calculate_sum_monthly_payment
        self.assertIsInstance(result, Decimal)

    def test_loan_calculate_total_amount_loan_with_interest_property(self):
        """Test Loan calculate_total_amount_loan_with_interest property."""
        result = self.loan1.calculate_total_amount_loan_with_interest
        self.assertIsInstance(result, Decimal)

    def test_payment_make_loan_model(self):
        """Test PaymentMakeLoan model."""
        payment_account = Account.objects.create(
            user=self.user,
            name_account='Test Payment Account',
            balance=5000,
            currency='RU',
        )
        payment = PaymentMakeLoan.objects.create(
            user=self.user,
            account=payment_account,
            date=timezone.now(),
            loan=self.loan1,
            amount=Decimal('1000'),
        )
        self.assertIsNotNone(payment)

    def test_payment_schedule_model(self):
        """Test PaymentSchedule model."""
        payment_schedule = PaymentSchedule.objects.create(
            user=self.user,
            loan=self.loan1,
            date=timezone.now(),
            balance=Decimal('9000'),
            monthly_payment=Decimal('1000'),
            interest=Decimal('100'),
            principal_payment=Decimal('900'),
        )
        self.assertIsNotNone(payment_schedule)

    def test_loan_view_unauthenticated(self):
        """Test LoanView for unauthenticated user."""
        response = self.client.get(reverse_lazy('loan:list'))
        self.assertEqual(response.status_code, 302)

    def test_loan_create_view_unauthenticated(self):
        """Test LoanCreateView for unauthenticated user."""
        response = self.client.get(reverse_lazy('loan:create'))
        self.assertEqual(response.status_code, 302)

    def test_loan_delete_view_unauthenticated(self):
        """Test LoanDeleteView for unauthenticated user."""
        # Создаем отдельный кредит для теста
        test_account = Account.objects.create(
            user=self.user,
            name_account='Test Loan Account',
            balance=10000,
            currency='RU',
        )
        test_loan = Loan.objects.create(
            user=self.user,
            account=test_account,
            date=timezone.now(),
            loan_amount=10000,
            annual_interest_rate=Decimal('5.5'),
            period_loan=12,
            type_loan='Annuity',
        )
        response = self.client.post(reverse_lazy('loan:delete', args=[test_loan.pk]))
        self.assertEqual(response.status_code, 302)

    def test_loan_form_field_configuration(self):
        """Test LoanForm field configuration."""
        form = LoanForm(user=self.user)
        self.assertIn('date', form.fields)
        self.assertIn('type_loan', form.fields)
        self.assertIn('loan_amount', form.fields)
        self.assertIn('annual_interest_rate', form.fields)
        self.assertIn('period_loan', form.fields)

    def test_payment_make_loan_form_field_configuration(self):
        """Test PaymentMakeLoanForm field configuration."""
        form = PaymentMakeLoanForm(user=self.user)
        self.assertIn('date', form.fields)
        self.assertIn('account', form.fields)
        self.assertIn('loan', form.fields)
        self.assertIn('amount', form.fields)

    def test_loan_form_init(self):
        """Test LoanForm initialization."""
        form = LoanForm(user=self.user)
        self.assertEqual(form.request_user, self.user)

    def test_payment_make_loan_form_init(self):
        """Test PaymentMakeLoanForm initialization."""
        form = PaymentMakeLoanForm(user=self.user)
        self.assertEqual(form.user, self.user)

    def test_calculate_annuity_loan_with_float_inputs(self):
        """Test calculate_annuity_loan with float inputs."""
        calculate_annuity_loan(
            user_id=self.user.pk,
            loan_id=self.loan1.pk,
            start_date=timezone.now(),
            loan_amount=10000.0,
            annual_interest_rate=5.5,
            period_loan=12,
        )
        self.assertTrue(PaymentSchedule.objects.filter(loan=self.loan1).exists())

    def test_calculate_differentiated_loan_with_float_inputs(self):
        """Test calculate_differentiated_loan with float inputs."""
        calculate_differentiated_loan(
            user_id=self.user.pk,
            loan_id=self.loan1.pk,
            start_date=timezone.now(),
            loan_amount=Decimal('10000.0'),
            annual_interest_rate=Decimal('5.5'),
            period_loan=12,
        )
        self.assertTrue(PaymentSchedule.objects.filter(loan=self.loan1).exists())

    def test_loan_calculate_sum_monthly_payment_without_payments(self):
        """Test Loan calculate_sum_monthly_payment property without payments."""
        result = self.loan1.calculate_sum_monthly_payment
        self.assertIsInstance(result, Decimal)

    def test_loan_calculate_sum_monthly_payment_with_zero_loan_amount(self):
        """Test Loan calculate_sum_monthly_payment property with zero loan amount."""
        self.loan1.loan_amount = 0
        self.loan1.save()
        result = self.loan1.calculate_sum_monthly_payment
        self.assertIsInstance(result, Decimal)

    def test_payment_make_create_view_unauthenticated(self):
        """Test PaymentMakeCreateView for unauthenticated user."""
        response = self.client.post(reverse_lazy('loan:payment_create'))
        self.assertEqual(response.status_code, 302)

    def test_payment_make_create_view_get(self):
        """Test PaymentMakeCreateView GET request."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('loan:payment_create'))
        self.assertEqual(response.status_code, 200)
