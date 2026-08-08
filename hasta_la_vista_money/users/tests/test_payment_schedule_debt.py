"""Tests for compute_total_payment_schedule_debt bank-code matching.

Regression coverage for a bug where Account.bank (a Bank ForeignKey) was
compared directly to bank-code strings such as 'SBERBANK', which is always
False for a model instance. This made the grace period collapse to the end
of the purchase month for every card, so on-time repayments made after that
date were not credited and the account kept showing a debt that was
actually paid off.
"""

from datetime import UTC, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import ACCOUNT_TYPE_CREDIT_CARD
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.services.summary_statistics_service import (
    compute_total_payment_schedule_debt,
)

User = get_user_model()


class ComputeTotalPaymentScheduleDebtTest(TestCase):
    """Verify Sberbank grace-period debt is cleared once repaid."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='debtuser',
            password='testpass123',  # nosec B106: test-only password
        )
        self.sberbank = Bank.objects.get(code='SBERBANK')
        self.card = Account.objects.create(
            user=self.user,
            name_account='Кредитная СберКарта',
            balance=Decimal('100000.00'),
            limit_credit=Decimal('100000.00'),
            currency='RUB',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            bank=self.sberbank,
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Покупки',
            type=TransactionType.EXPENSE,
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Погашение',
            type=TransactionType.INCOME,
        )
        container = ApplicationContainer()
        self.account_service = container.finance_account.account_service()

    def test_debt_cleared_when_paid_within_grace_period(self) -> None:
        """A payment made after the purchase month, but inside Sberbank's
        3-month grace period, must clear the debt for that month.
        """
        Transaction.objects.create(
            user=self.user,
            account=self.card,
            category=self.expense_category,
            amount=Decimal('10000.00'),
            date=datetime(2026, 3, 10, 12, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.card,
            category=self.income_category,
            amount=Decimal('10000.00'),
            date=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            type=TransactionType.INCOME,
        )

        total_debt = compute_total_payment_schedule_debt(
            Account.objects.filter(pk=self.card.pk),
            self.account_service,
        )

        self.assertEqual(total_debt, Decimal(0))
