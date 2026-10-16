"""Tests for the «Корректировка остатка» web operation."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_feed import list_operations
from hasta_la_vista_money.transactions.models import (
    SystemCategoryKind,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User

TEST_PASSWORD = 'pwd123456!'  # nosec B105


class BalanceAdjustmentViewTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='adj-user',
            password=TEST_PASSWORD,
        )
        self.account = self._account(self.user, constants.ACCOUNT_TYPE_DEBIT)
        self.client.force_login(self.user)

    @staticmethod
    def _account(user: User, type_account: str, **extra: object) -> Account:
        return Account.objects.create(
            user=user,
            name_account='Счёт',
            type_account=type_account,
            balance=Decimal('100.00'),
            currency='RUB',
            **extra,
        )

    def _post(self, account: Account, actual: str):  # type: ignore[no-untyped-def]
        return self.client.post(
            reverse('finance_account:adjust_balance', args=[account.pk]),
            {'actual_balance': actual},
        )

    def _balance(self, account: Account) -> Decimal:
        account.refresh_from_db()
        return account.balance

    def test_form_page_opens(self) -> None:
        response = self.client.get(
            reverse(
                'finance_account:adjust_balance',
                args=[self.account.pk],
            ),
        )
        self.assertEqual(response.status_code, 200)

    def test_higher_actual_creates_income(self) -> None:
        self._post(self.account, '150.50')

        movement = Transaction.objects.get(account=self.account)
        self.assertEqual(movement.type, TransactionType.INCOME)
        self.assertEqual(movement.amount, Decimal('50.50'))
        self.assertEqual(
            movement.category.system_kind,
            SystemCategoryKind.BALANCE_ADJUSTMENT,
        )
        self.assertEqual(self._balance(self.account), Decimal('150.50'))

    def test_lower_actual_creates_expense(self) -> None:
        self._post(self.account, '40.00')

        movement = Transaction.objects.get(account=self.account)
        self.assertEqual(movement.type, TransactionType.EXPENSE)
        self.assertEqual(movement.amount, Decimal('60.00'))
        self.assertEqual(self._balance(self.account), Decimal('40.00'))

    def test_difference_uses_balance_at_posting_time(self) -> None:
        Account.objects.filter(pk=self.account.pk).update(
            balance=Decimal('130.00'),
        )

        self._post(self.account, '150.00')

        movement = Transaction.objects.get(account=self.account)
        self.assertEqual(movement.amount, Decimal('20.00'))
        self.assertEqual(self._balance(self.account), Decimal('150.00'))

    def test_equal_actual_creates_nothing(self) -> None:
        response = self._post(self.account, '100.00')

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self._balance(self.account), Decimal('100.00'))

    def test_credit_card_adjusts_both_ways(self) -> None:
        card = self._account(self.user, constants.ACCOUNT_TYPE_CREDIT_CARD)

        self._post(card, '130.00')
        self.assertEqual(self._balance(card), Decimal('130.00'))
        self._post(card, '10.00')
        self.assertEqual(self._balance(card), Decimal('10.00'))
        self.assertEqual(Transaction.objects.filter(account=card).count(), 2)

    def test_refused_accounts_keep_balance(self) -> None:
        other = User.objects.create_user(
            username='other',
            password=TEST_PASSWORD,
        )
        deposit = self._account(self.user, constants.ACCOUNT_TYPE_DEBIT)
        Account.objects.filter(pk=deposit.pk).update(
            type_account=constants.ACCOUNT_TYPE_DEPOSIT,
        )
        refused = [
            self._account(other, constants.ACCOUNT_TYPE_DEBIT),
            deposit,
            self._account(
                self.user,
                constants.ACCOUNT_TYPE_DEBIT,
                archived_at=timezone.now(),
            ),
        ]
        for account in refused:
            self._post(account, '999.00')
            self.assertEqual(self._balance(account), Decimal('100.00'))
        self.assertFalse(Transaction.objects.exists())

    def test_feed_shows_adjustment_with_before_and_after(self) -> None:
        self._post(self.account, '150.00')

        page = list_operations(
            AuditLog.objects.filter(
                kind=AuditOperationKind.BALANCE_ADJUSTMENT,
            ),
            page=1,
            page_size=10,
        )

        self.assertEqual(len(page.operations), 1)
        operation = page.operations[0]
        self.assertEqual(operation.title, 'Корректировка остатка')
        chip = operation.balance_chips[0]
        self.assertIn('100', chip.before)
        self.assertIn('150', chip.after)
