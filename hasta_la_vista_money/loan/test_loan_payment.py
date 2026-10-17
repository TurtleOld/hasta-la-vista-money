"""Tests for posting a loan payment as a financial movement."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.loan.models import (
    Loan,
    PaymentMakeLoan,
    PaymentSchedule,
)
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_feed import list_operations
from hasta_la_vista_money.users.models import User


class PostLoanPaymentTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='loan-user')
        self.source = self._account(self.user, 'Карта', '1000.00')
        self.loan = self._loan(self.user)
        self.client.force_login(self.user)

    @staticmethod
    def _account(user: User, name: str, balance: str) -> Account:
        return Account.objects.create(
            user=user,
            name_account=name,
            balance=Decimal(balance),
            currency='RUB',
        )

    def _loan(self, user: User) -> Loan:
        return Loan.objects.create(
            user=user,
            account=self._account(user, 'Кредитный счёт', '2000.00'),
            date=timezone.now(),
            loan_amount=Decimal('5000.00'),
            annual_interest_rate=Decimal('10.00'),
            period_loan=12,
        )

    def _post(
        self,
        loan: Loan,
        account: Account | None,
        amount: str = '300.00',
    ) -> dict[str, object]:
        response = self.client.post(
            reverse('loan:payment_create'),
            {
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'account': account.pk if account else '',
                'loan': loan.pk,
                'amount': amount,
            },
        )
        return dict(response.json())

    @staticmethod
    def _balance(account: Account) -> Decimal:
        account.refresh_from_db()
        return account.balance

    def test_payment_from_account_moves_both_balances(self) -> None:
        result = self._post(self.loan, self.source)

        self.assertTrue(result['success'])
        self.assertEqual(self._balance(self.source), Decimal('700.00'))
        self.assertEqual(
            self._balance(self.loan.account),
            Decimal('2300.00'),
        )
        payment = PaymentMakeLoan.objects.get()
        self.assertTrue(payment.is_posted)
        self.assertEqual(payment.account, self.source)

    def test_external_source_changes_only_loan_account(self) -> None:
        result = self._post(self.loan, None)

        self.assertTrue(result['success'])
        self.assertEqual(self._balance(self.source), Decimal('1000.00'))
        self.assertEqual(
            self._balance(self.loan.account),
            Decimal('2300.00'),
        )
        payment = PaymentMakeLoan.objects.get()
        self.assertIsNone(payment.account)
        self.assertTrue(payment.is_posted)

    def test_insufficient_funds_rejected_without_changes(self) -> None:
        result = self._post(self.loan, self.source, '1000.01')

        self.assertFalse(result['success'])
        self.assertFalse(PaymentMakeLoan.objects.exists())
        self.assertEqual(self._balance(self.source), Decimal('1000.00'))
        self.assertEqual(
            self._balance(self.loan.account),
            Decimal('2000.00'),
        )

    def test_foreign_source_rejected(self) -> None:
        other = User.objects.create_user(username='other')
        foreign = self._account(other, 'Чужой', '1000.00')

        result = self._post(self.loan, foreign)

        self.assertFalse(result['success'])
        self.assertFalse(PaymentMakeLoan.objects.exists())
        self.assertEqual(self._balance(foreign), Decimal('1000.00'))

    def test_foreign_loan_rejected(self) -> None:
        other = User.objects.create_user(username='other')
        foreign_loan = self._loan(other)

        result = self._post(foreign_loan, self.source)

        self.assertFalse(result['success'])
        self.assertFalse(PaymentMakeLoan.objects.exists())
        self.assertEqual(self._balance(self.source), Decimal('1000.00'))
        self.assertEqual(
            self._balance(foreign_loan.account),
            Decimal('2000.00'),
        )

    def test_overpayment_rejected_without_changes(self) -> None:
        result = self._post(self.loan, None, '3000.01')

        self.assertFalse(result['success'])
        self.assertFalse(PaymentMakeLoan.objects.exists())
        self.assertEqual(
            self._balance(self.loan.account),
            Decimal('2000.00'),
        )

    def test_deposit_source_rejected(self) -> None:
        deposit = Account.objects.create_deposit(
            user=self.user,
            name_account='Вклад',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        service = ApplicationContainer().loan.loan_payment_service()

        with self.assertRaises(ValidationError):
            service.post_payment(
                user=self.user,
                loan_id=self.loan.pk,
                account_id=deposit.pk,
                amount=Decimal('100.00'),
                date=timezone.now(),
            )

        self.assertFalse(PaymentMakeLoan.objects.exists())
        self.assertEqual(self._balance(deposit), Decimal('1000.00'))

    def test_audit_shows_balances_of_both_accounts(self) -> None:
        self._post(self.loan, self.source)

        page = list_operations(
            AuditLog.objects.filter(kind=AuditOperationKind.LOAN_PAYMENT),
            page=1,
            page_size=10,
        )

        self.assertEqual(len(page.operations), 1)
        operation = page.operations[0]
        self.assertEqual(operation.title, 'Платёж по кредиту')
        self.assertEqual(len(operation.balance_chips), 2)

    def test_list_marks_unposted_payment(self) -> None:
        PaymentMakeLoan.objects.create(
            user=self.user,
            account=self.source,
            date=timezone.now(),
            loan=self.loan,
            amount=Decimal('100.00'),
            is_posted=False,
        )
        PaymentSchedule.objects.create(
            user=self.user,
            loan=self.loan,
            date=timezone.now(),
            balance=Decimal('4900.00'),
            monthly_payment=Decimal('100.00'),
            interest=Decimal('10.00'),
            principal_payment=Decimal('90.00'),
        )

        response = self.client.get(reverse('loan:list'))

        self.assertContains(response, 'не проведён')
        self.assertEqual(self._balance(self.source), Decimal('1000.00'))


class PaymentMigrationTest(TransactionTestCase):
    """Existing payments become unposted and keep every balance."""

    migrate_from = [('loan', '0004_alter_loan_annual_interest_rate_and_more')]
    migrate_to = [('loan', '0005_loan_payment_posting')]

    def tearDown(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_payments_are_unposted(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        user = User.objects.create_user(username='migration-user')
        account = Account.objects.create(
            user=user,
            name_account='Карта',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        loan = old_apps.get_model('loan', 'Loan').objects.create(
            user_id=user.pk,
            account_id=account.pk,
            date=timezone.now(),
            loan_amount=Decimal('5000.00'),
            annual_interest_rate=Decimal('10.00'),
            period_loan=12,
        )
        old_apps.get_model('loan', 'PaymentMakeLoan').objects.create(
            user_id=user.pk,
            account_id=account.pk,
            date=timezone.now(),
            loan_id=loan.pk,
            amount=Decimal('100.00'),
        )

        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(self.migrate_to)

        self.assertFalse(PaymentMakeLoan.objects.get().is_posted)
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal('1000.00'))
