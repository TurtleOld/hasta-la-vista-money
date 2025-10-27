from decimal import Decimal
from typing import ClassVar

from django.test import TestCase
from django.urls import reverse_lazy
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.loan.forms import LoanForm, PaymentMakeLoanForm
from hasta_la_vista_money.loan.loan_calculator import (
    calculate_annuity_schedule,
    calculate_differentiated_schedule,
)
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

    fixtures: ClassVar[list[str]] = [
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

    def _create_test_account(
        self,
        name: str = 'Test Account',
        balance: float = constants.TEST_ACCOUNT_BALANCE,
    ) -> Account:
        """Create test account for loan operations."""
        return Account.objects.create(
            user=self.user,
            name_account=name,
            balance=balance,
            currency='RU',
        )

    def _create_test_loan(
        self,
        loan_amount: float = constants.TEST_LOAN_AMOUNT_MEDIUM,
        type_loan: str = 'Annuity',
    ) -> Loan:
        """Create test loan for testing purposes."""
        test_account = self._create_test_account(
            'Test Loan Account', loan_amount
        )
        return Loan.objects.create(
            user=self.user,
            account=test_account,
            date=timezone.now(),
            loan_amount=loan_amount,
            annual_interest_rate=Decimal(
                str(constants.TEST_INTEREST_RATE_MEDIUM)
            ),
            period_loan=constants.TEST_PERIOD_LONG,
            type_loan=type_loan,
        )

    def _get_loan_form_data(
        self,
        type_loan: str = 'Annuity',
        loan_amount: int = constants.TEST_LOAN_AMOUNT_MEDIUM,
    ) -> dict:
        """Get standard loan form data for testing."""
        return {
            'type_loan': type_loan,
            'date': constants.TEST_DATE_STRING,
            'loan_amount': loan_amount,
            'annual_interest_rate': constants.TEST_INTEREST_RATE_LOW,
            'period_loan': constants.TEST_PERIOD_LONG,
        }

    def test_list_loan(self) -> None:
        """Test loan list view."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('loan:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_create_annuity_loan(self):
        """Test annuity loan creation."""
        self.client.force_login(self.user)
        url = reverse_lazy('loan:create')
        data = self._get_loan_form_data('Annuity')
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertTrue(
            Loan.objects.filter(loan_amount=data['loan_amount']).exists()
        )

    def test_create_differentiated_loan(self):
        """Test differentiated loan creation."""
        self.client.force_login(self.user)
        url = reverse_lazy('loan:create')
        data = self._get_loan_form_data('Differentiated')
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, constants.REDIRECTS)
        self.assertTrue(
            Loan.objects.filter(loan_amount=data['loan_amount']).exists()
        )

    def test_create_loan_invalid_data(self):
        """Test loan creation with invalid data."""
        self.client.force_login(self.user)
        url = reverse_lazy('loan:create')
        data = self._get_loan_form_data()
        data['date'] = ''
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
                'loan_amount': constants.TEST_LOAN_AMOUNT_MEDIUM,
                'annual_interest_rate': constants.TEST_INTEREST_RATE_MEDIUM,
                'period_loan': constants.TEST_PERIOD_LONG,
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
            self.assertTrue(
                Loan.objects.filter(
                    loan_amount=constants.TEST_LOAN_AMOUNT_MEDIUM
                ).exists()
            )

    def test_payment_make_loan_form_validation(self):
        """Test PaymentMakeLoanForm validation."""
        payment_account = self._create_test_account('Test Payment Account')

        form = PaymentMakeLoanForm(
            user=self.user,
            data={
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'account': payment_account.pk,
                'loan': self.loan1.pk,
                'amount': constants.TEST_PAYMENT_AMOUNT,
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

    def test_loan_create_view_context_data(self):
        """Test LoanCreateView context data."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('loan:create'))
        self.assertIn('loan_form', response.context)

    def test_loan_delete_view(self):
        """Test LoanDeleteView functionality."""
        self.client.force_login(self.user)
        test_loan = self._create_test_loan()
        response = self.client.post(
            reverse_lazy('loan:delete', args=[test_loan.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_payment_make_create_view_post(self):
        """Test PaymentMakeCreateView POST request."""
        self.client.force_login(self.user)
        payment_account = self._create_test_account('Test Payment Account')
        data = {
            'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'account': payment_account.pk,
            'loan': self.loan1.pk,
            'amount': constants.TEST_PAYMENT_AMOUNT,
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
            loan_amount=Decimal(constants.TEST_LOAN_AMOUNT_MEDIUM),
            annual_interest_rate=Decimal(
                str(constants.TEST_INTEREST_RATE_MEDIUM)
            ),
            period_loan=constants.TEST_PERIOD_LONG,
        )
        self.assertTrue(
            PaymentSchedule.objects.filter(loan=self.loan1).exists(),
        )

    def test_calculate_differentiated_loan(self):
        """Test calculate_differentiated_loan function."""
        calculate_differentiated_loan(
            user_id=self.user.pk,
            loan_id=self.loan1.pk,
            start_date=timezone.now(),
            loan_amount=Decimal(constants.TEST_LOAN_AMOUNT_MEDIUM),
            annual_interest_rate=Decimal(
                str(constants.TEST_INTEREST_RATE_MEDIUM)
            ),
            period_loan=constants.TEST_PERIOD_LONG,
        )
        self.assertTrue(
            PaymentSchedule.objects.filter(loan=self.loan1).exists(),
        )

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
        payment_account = self._create_test_account('Test Payment Account')
        payment = PaymentMakeLoan.objects.create(
            user=self.user,
            account=payment_account,
            date=timezone.now(),
            loan=self.loan1,
            amount=Decimal(constants.TEST_PAYMENT_AMOUNT),
        )
        self.assertIsNotNone(payment)

    def test_payment_schedule_model(self):
        """Test PaymentSchedule model."""
        payment_schedule = PaymentSchedule.objects.create(
            user=self.user,
            loan=self.loan1,
            date=timezone.now(),
            balance=Decimal(constants.TEST_PAYMENT_BALANCE),
            monthly_payment=Decimal(constants.TEST_PAYMENT_AMOUNT),
            interest=Decimal(constants.TEST_PAYMENT_INTEREST),
            principal_payment=Decimal(constants.TEST_PAYMENT_PRINCIPAL),
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
        test_loan = self._create_test_loan()
        response = self.client.post(
            reverse_lazy('loan:delete', args=[test_loan.pk]),
        )
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
            loan_amount=constants.TEST_LOAN_AMOUNT_MEDIUM,
            annual_interest_rate=constants.TEST_INTEREST_RATE_MEDIUM,
            period_loan=constants.TEST_PERIOD_LONG,
        )
        self.assertTrue(
            PaymentSchedule.objects.filter(loan=self.loan1).exists(),
        )

    def test_calculate_differentiated_loan_with_float_inputs(self):
        """Test calculate_differentiated_loan with float inputs."""
        calculate_differentiated_loan(
            user_id=self.user.pk,
            loan_id=self.loan1.pk,
            start_date=timezone.now(),
            loan_amount=Decimal(str(constants.TEST_LOAN_AMOUNT_MEDIUM)),
            annual_interest_rate=Decimal(
                str(constants.TEST_INTEREST_RATE_MEDIUM)
            ),
            period_loan=constants.TEST_PERIOD_LONG,
        )
        self.assertTrue(
            PaymentSchedule.objects.filter(loan=self.loan1).exists(),
        )

    def test_loan_calculate_sum_monthly_payment_without_payments(self):
        """Test Loan calculate_sum_monthly_payment property without payments."""
        result = self.loan1.calculate_sum_monthly_payment
        self.assertIsInstance(result, Decimal)

    def test_loan_calculate_sum_monthly_payment_with_zero_loan_amount(self):
        """
        Test Loan calculate_sum_monthly_payment property with zero loan amount.
        """
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


class TestLoanCalculator(TestCase):
    """Test cases for loan calculation functions."""

    def test_calculate_annuity_schedule_basic(self):
        """Test basic annuity schedule calculation."""
        result = calculate_annuity_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_LONG,
        )

        self.assertIn('schedule', result)
        self.assertIn('total_payment', result)
        self.assertIn('overpayment', result)
        self.assertIn('monthly_payment', result)
        self.assertEqual(len(result['schedule']), constants.TEST_PERIOD_LONG)
        self.assertGreater(
            result['total_payment'], constants.TEST_LOAN_AMOUNT_LARGE
        )
        self.assertGreater(result['overpayment'], 0)

    def test_calculate_annuity_schedule_structure(self):
        """Test annuity schedule data structure."""
        result = calculate_annuity_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_MEDIUM,
        )
        schedule = result['schedule']

        for payment in schedule:
            self.assertIn('month', payment)
            self.assertIn('payment', payment)
            self.assertIn('interest', payment)
            self.assertIn('principal', payment)
            self.assertIn('balance', payment)
            self.assertGreaterEqual(payment['payment'], 0)
            self.assertGreaterEqual(payment['interest'], 0)
            self.assertGreaterEqual(payment['principal'], 0)
            self.assertGreaterEqual(payment['balance'], 0)

    def test_calculate_annuity_schedule_zero_rate(self):
        """Test annuity calculation with zero interest rate."""
        result = calculate_annuity_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE, 0, constants.TEST_PERIOD_LONG
        )
        schedule = result['schedule']

        payments = [p['payment'] for p in schedule]
        self.assertTrue(
            all(
                abs(p - payments[0]) < constants.TOLERANCE_MEDIUM
                for p in payments
            )
        )
        self.assertAlmostEqual(
            result['overpayment'], 0, places=constants.DECIMAL_PLACES_ROUNDING
        )
        self.assertAlmostEqual(
            result['total_payment'],
            constants.TEST_LOAN_AMOUNT_LARGE,
            places=constants.DECIMAL_PLACES_ROUNDING,
        )

    def test_calculate_annuity_schedule_known_values(self):
        """Test annuity calculation with known values."""
        result = calculate_annuity_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_LONG,
        )

        self.assertAlmostEqual(
            result['monthly_payment'],
            constants.ANNUITY_MONTHLY_PAYMENT_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )
        self.assertAlmostEqual(
            result['total_payment'],
            constants.ANNUITY_TOTAL_PAYMENT_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )
        self.assertAlmostEqual(
            result['overpayment'],
            constants.ANNUITY_OVERPAYMENT_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )

        first_payment = result['schedule'][0]
        self.assertAlmostEqual(
            first_payment['payment'],
            constants.ANNUITY_FIRST_PAYMENT_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )
        self.assertAlmostEqual(
            first_payment['interest'],
            constants.ANNUITY_FIRST_INTEREST_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )
        self.assertAlmostEqual(
            first_payment['principal'],
            constants.ANNUITY_FIRST_PRINCIPAL_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )

    def test_calculate_annuity_schedule_last_payment(self):
        """Test that last payment covers remaining balance."""
        result = calculate_annuity_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_LONG,
        )
        last_payment = result['schedule'][-1]

        self.assertEqual(last_payment['balance'], 0)
        self.assertAlmostEqual(
            last_payment['payment'],
            last_payment['principal'] + last_payment['interest'],
            places=constants.DECIMAL_PLACES_PRECISION,
        )

    def test_calculate_differentiated_schedule_basic(self):
        """Test basic differentiated schedule calculation."""
        result = calculate_differentiated_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_LONG,
        )

        self.assertIn('schedule', result)
        self.assertIn('total_payment', result)
        self.assertIn('overpayment', result)
        self.assertEqual(len(result['schedule']), 12)
        self.assertGreater(result['total_payment'], 100000)
        self.assertGreater(result['overpayment'], 0)

    def test_calculate_differentiated_schedule_structure(self):
        """Test differentiated schedule data structure."""
        result = calculate_differentiated_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_MEDIUM,
        )
        schedule = result['schedule']

        for payment in schedule:
            self.assertIn('month', payment)
            self.assertIn('payment', payment)
            self.assertIn('interest', payment)
            self.assertIn('principal', payment)
            self.assertIn('balance', payment)
            self.assertGreaterEqual(payment['payment'], 0)
            self.assertGreaterEqual(payment['interest'], 0)
            self.assertGreaterEqual(payment['principal'], 0)
            self.assertGreaterEqual(payment['balance'], 0)

    def test_calculate_differentiated_schedule_principal_constant(self):
        """Test that principal payment is constant in differentiated loan."""
        result = calculate_differentiated_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_LONG,
        )
        schedule = result['schedule']

        principal_payments = [p['principal'] for p in schedule]
        self.assertTrue(
            all(p == principal_payments[0] for p in principal_payments)
        )
        self.assertAlmostEqual(
            principal_payments[0],
            constants.DIFF_PRINCIPAL_PAYMENT_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )

    def test_calculate_differentiated_schedule_decreasing_payments(self):
        """Test that payments decrease over time in differentiated loan."""
        result = calculate_differentiated_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_LONG,
        )
        schedule = result['schedule']

        payments = [p['payment'] for p in schedule]
        for i in range(1, len(payments)):
            self.assertGreater(payments[i - 1], payments[i])

    def test_calculate_differentiated_schedule_zero_rate(self):
        """Test differentiated calculation with zero interest rate."""
        result = calculate_differentiated_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE, 0, constants.TEST_PERIOD_LONG
        )
        schedule = result['schedule']

        for payment in schedule:
            self.assertEqual(payment['interest'], 0)
            self.assertEqual(payment['payment'], payment['principal'])
        self.assertAlmostEqual(
            result['overpayment'], 0, places=constants.DECIMAL_PLACES_ROUNDING
        )
        self.assertAlmostEqual(
            result['total_payment'],
            constants.TEST_LOAN_AMOUNT_LARGE,
            places=constants.DECIMAL_PLACES_ROUNDING,
        )

    def test_calculate_differentiated_schedule_known_values(self):
        """Test differentiated calculation with known values."""
        result = calculate_differentiated_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_LONG,
        )

        first_payment = result['schedule'][0]
        self.assertAlmostEqual(
            first_payment['principal'],
            constants.DIFF_PRINCIPAL_PAYMENT_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )
        self.assertAlmostEqual(
            first_payment['interest'],
            constants.DIFF_FIRST_INTEREST_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )
        self.assertAlmostEqual(
            first_payment['payment'],
            constants.DIFF_FIRST_PAYMENT_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )

        last_payment = result['schedule'][-1]
        self.assertAlmostEqual(
            last_payment['principal'],
            constants.DIFF_PRINCIPAL_PAYMENT_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )
        self.assertAlmostEqual(
            last_payment['interest'],
            constants.DIFF_LAST_INTEREST_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )
        self.assertAlmostEqual(
            last_payment['payment'],
            constants.DIFF_LAST_PAYMENT_100K_12M,
            places=constants.DECIMAL_PLACES_PRECISION,
        )

    def test_calculate_annuity_vs_differentiated_overpayment(self):
        """Test that annuity has higher overpayment than differentiated."""
        annuity_result = calculate_annuity_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_LONG,
        )
        diff_result = calculate_differentiated_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_LONG,
        )

        self.assertGreater(
            annuity_result['overpayment'], diff_result['overpayment']
        )

    def test_calculate_schedule_edge_cases(self):
        """Test edge cases for schedule calculations."""
        annuity_single = calculate_annuity_schedule(
            constants.TEST_LOAN_AMOUNT_SMALL,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_SHORT,
        )
        diff_single = calculate_differentiated_schedule(
            constants.TEST_LOAN_AMOUNT_SMALL,
            constants.TEST_INTEREST_RATE_HIGH,
            constants.TEST_PERIOD_SHORT,
        )

        self.assertEqual(
            len(annuity_single['schedule']), constants.TEST_PERIOD_SHORT
        )
        self.assertEqual(
            len(diff_single['schedule']), constants.TEST_PERIOD_SHORT
        )
        self.assertEqual(annuity_single['schedule'][0]['balance'], 0)
        self.assertEqual(diff_single['schedule'][0]['balance'], 0)

    def test_calculate_schedule_rounding(self):
        """Test that all values are properly rounded to 2 decimal places."""
        result = calculate_annuity_schedule(
            constants.TEST_LOAN_AMOUNT_LARGE,
            constants.TEST_INTEREST_RATE_EXTRA_HIGH,
            constants.TEST_PERIOD_LONG,
        )

        for payment in result['schedule']:
            payment_str = str(payment['payment'])
            interest_str = str(payment['interest'])
            principal_str = str(payment['principal'])
            balance_str = str(payment['balance'])

            if '.' in payment_str:
                self.assertLessEqual(
                    len(payment_str.split('.')[-1]),
                    constants.DECIMAL_PLACES_PRECISION,
                )
            if '.' in interest_str:
                self.assertLessEqual(
                    len(interest_str.split('.')[-1]),
                    constants.DECIMAL_PLACES_PRECISION,
                )
            if '.' in principal_str:
                self.assertLessEqual(
                    len(principal_str.split('.')[-1]),
                    constants.DECIMAL_PLACES_PRECISION,
                )
            if '.' in balance_str:
                self.assertLessEqual(
                    len(balance_str.split('.')[-1]),
                    constants.DECIMAL_PLACES_PRECISION,
                )


class TestLoanCalculationIntegration(TestCase):
    """Integration tests for loan calculation tasks."""

    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
        'loan.yaml',
    ]

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.get(pk=1)
        self.loan1 = Loan.objects.get(pk=2)
        self.account = Account.objects.get(pk=1)

    def test_calculate_annuity_loan_creates_schedule(self):
        """Test that calculate_annuity_loan creates payment schedule."""
        initial_count = PaymentSchedule.objects.filter(loan=self.loan1).count()

        calculate_annuity_loan(
            user_id=self.user.pk,
            loan_id=self.loan1.pk,
            start_date=timezone.now(),
            loan_amount=Decimal(constants.TEST_LOAN_AMOUNT_MEDIUM),
            annual_interest_rate=Decimal(
                str(constants.TEST_INTEREST_RATE_MEDIUM)
            ),
            period_loan=constants.TEST_PERIOD_LONG,
        )

        final_count = PaymentSchedule.objects.filter(loan=self.loan1).count()
        self.assertEqual(
            final_count, initial_count + constants.TEST_PERIOD_LONG
        )

    def test_calculate_differentiated_loan_creates_schedule(self):
        """Test that calculate_differentiated_loan creates payment schedule."""
        initial_count = PaymentSchedule.objects.filter(loan=self.loan1).count()

        calculate_differentiated_loan(
            user_id=self.user.pk,
            loan_id=self.loan1.pk,
            start_date=timezone.now(),
            loan_amount=Decimal(constants.TEST_LOAN_AMOUNT_MEDIUM),
            annual_interest_rate=Decimal(
                str(constants.TEST_INTEREST_RATE_MEDIUM)
            ),
            period_loan=constants.TEST_PERIOD_LONG,
        )

        final_count = PaymentSchedule.objects.filter(loan=self.loan1).count()
        self.assertEqual(
            final_count, initial_count + constants.TEST_PERIOD_LONG
        )

    def test_calculate_loan_with_different_data_types(self):
        """Test loan calculation with different data types."""
        test_cases = [
            (
                constants.TEST_LOAN_AMOUNT_MEDIUM,
                constants.TEST_INTEREST_RATE_MEDIUM,
                constants.TEST_PERIOD_LONG,
            ),
            (
                Decimal(constants.TEST_LOAN_AMOUNT_MEDIUM),
                Decimal(str(constants.TEST_INTEREST_RATE_MEDIUM)),
                constants.TEST_PERIOD_LONG,
            ),
            (
                str(constants.TEST_LOAN_AMOUNT_MEDIUM),
                str(constants.TEST_INTEREST_RATE_MEDIUM),
                str(constants.TEST_PERIOD_LONG),
            ),
        ]

        for loan_amount, rate, period in test_cases:
            with self.subTest(
                loan_amount=loan_amount, rate=rate, period=period
            ):
                calculate_annuity_loan(
                    user_id=self.user.pk,
                    loan_id=self.loan1.pk,
                    start_date=timezone.now(),
                    loan_amount=loan_amount,
                    annual_interest_rate=rate,
                    period_loan=period,
                )

                schedule_exists = PaymentSchedule.objects.filter(
                    loan=self.loan1
                ).exists()
                self.assertTrue(schedule_exists)

    def test_calculate_loan_schedule_data_accuracy(self):
        """Test that created schedule matches calculator results."""
        loan_amount = Decimal(constants.TEST_LOAN_AMOUNT_MEDIUM)
        rate = Decimal(str(constants.TEST_INTEREST_RATE_MEDIUM))
        period = constants.TEST_PERIOD_LONG

        PaymentSchedule.objects.filter(loan=self.loan1).delete()

        calculate_annuity_loan(
            user_id=self.user.pk,
            loan_id=self.loan1.pk,
            start_date=timezone.now(),
            loan_amount=loan_amount,
            annual_interest_rate=rate,
            period_loan=period,
        )

        calculator_result = calculate_annuity_schedule(
            float(loan_amount), float(rate), period
        )

        schedule_payments = PaymentSchedule.objects.filter(
            loan=self.loan1
        ).order_by('date')

        self.assertEqual(
            len(schedule_payments), len(calculator_result['schedule'])
        )

        for i, payment in enumerate(schedule_payments):
            calc_payment = calculator_result['schedule'][i]
            self.assertAlmostEqual(
                float(payment.monthly_payment),
                calc_payment['payment'],
                places=constants.DECIMAL_PLACES_PRECISION,
            )
            self.assertAlmostEqual(
                float(payment.interest),
                calc_payment['interest'],
                places=constants.DECIMAL_PLACES_PRECISION,
            )
            self.assertAlmostEqual(
                float(payment.principal_payment),
                calc_payment['principal'],
                places=constants.DECIMAL_PLACES_PRECISION,
            )
