"""Tests for balance-derived credit-card debt.

Credit-card debt is the credit limit minus the account balance. It must
not be reconstructed from the tracked movements: debt that predates the
user's tracking, or falls outside the selected period, still counts.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_DEBIT_CARD,
)
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.finance_account.services.credit_debt import (
    card_debt_for_balance,
    compute_total_credit_debt,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)

User = get_user_model()


class CardDebtForBalanceTest(TestCase):
    """Unit tests for the balance-based debt primitives."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='debtuser',
            password='testpass123',  # nosec B106: test-only password
        )
        self.sberbank = Bank.objects.get(code='SBERBANK')

    def _card(
        self,
        balance: str,
        limit: str | None = '100000.00',
    ) -> Account:
        return Account.objects.create(
            user=self.user,
            name_account='Кредитная СберКарта',
            balance=Decimal(balance),
            limit_credit=Decimal(limit) if limit is not None else None,
            currency='RUB',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            bank=self.sberbank,
        )

    def test_debt_is_limit_minus_balance(self) -> None:
        card = self._card(balance='81529.43')

        self.assertEqual(
            card_debt_for_balance(card, card.balance),
            Decimal('18470.57'),
        )

    def test_debt_is_zero_when_balance_reaches_limit(self) -> None:
        card = self._card(balance='100000.00')

        self.assertEqual(
            card_debt_for_balance(card, card.balance),
            Decimal(0),
        )

    def test_debt_is_zero_without_limit(self) -> None:
        card = self._card(balance='1000.00', limit=None)

        self.assertEqual(
            card_debt_for_balance(card, card.balance),
            Decimal(0),
        )

    def test_total_sums_only_credit_accounts(self) -> None:
        self._card(balance='81529.43')
        Account.objects.create(
            user=self.user,
            name_account='Дебетовая карта',
            balance=Decimal('1000.00'),
            currency='RUB',
            type_account=ACCOUNT_TYPE_DEBIT_CARD,
            bank=self.sberbank,
        )

        total = compute_total_credit_debt(
            Account.objects.by_user(self.user),
        )

        self.assertEqual(total, Decimal('18470.57'))

    def test_total_counts_debt_that_predates_tracked_movements(self) -> None:
        card = self._card(balance='90000.00')
        category = Category.objects.create(
            user=self.user,
            name='Покупки',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=card,
            category=category,
            amount=Decimal('10000.00'),
            date=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )

        total = compute_total_credit_debt(
            Account.objects.by_user(self.user),
        )

        self.assertEqual(total, Decimal('10000.00'))

    def test_total_is_zero_after_repayment_restores_balance(self) -> None:
        card = self._card(balance='95000.00')
        category = Category.objects.create(
            user=self.user,
            name='Погашение',
            type=TransactionType.INCOME,
        )
        Transaction.objects.create(
            user=self.user,
            account=card,
            category=category,
            amount=Decimal('5000.00'),
            date=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            type=TransactionType.INCOME,
        )
        card.balance = Decimal('100000.00')
        card.save(update_fields=['balance'])

        total = compute_total_credit_debt(
            Account.objects.by_user(self.user),
        )

        self.assertEqual(total, Decimal(0))

    def test_total_debt_differs_from_period_debt(self) -> None:
        card = self._card(balance='94000.00')
        expense_category = Category.objects.create(
            user=self.user,
            name='Покупки',
            type=TransactionType.EXPENSE,
        )
        income_category = Category.objects.create(
            user=self.user,
            name='Погашение',
            type=TransactionType.INCOME,
        )
        Transaction.objects.create(
            user=self.user,
            account=card,
            category=expense_category,
            amount=Decimal('10000.00'),
            date=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=card,
            category=income_category,
            amount=Decimal('4000.00'),
            date=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
            type=TransactionType.INCOME,
        )
        container = ApplicationContainer()
        account_service = container.finance_account.account_service()

        period_debt = account_service.get_credit_card_debt(
            card,
            date(2026, 8, 1),
            date(2026, 8, 31),
        )

        self.assertEqual(period_debt, Decimal('10000.00'))
        self.assertEqual(
            card_debt_for_balance(card, card.balance),
            Decimal('6000.00'),
        )
