"""Tests for BalanceHistoryService.balance_at reconstructing past balances
from receipts, transactions, transfers, and registered movement sources."""

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.deposits.models import Deposit, DepositPrincipalEvent
from hasta_la_vista_money.finance_account.models import (
    Account,
    Bank,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.services import (
    BalanceHistoryService,
)
from hasta_la_vista_money.receipts.models import Receipt, Seller
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


class BalanceHistoryServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        self.moment = timezone.now() - timedelta(days=2)
        self.service = BalanceHistoryService(movement_sources=[])

    def test_no_later_events_returns_current_balance(self) -> None:
        self.assertEqual(
            self.service.balance_at(self.account, self.moment),
            Decimal('1000.00'),
        )

    def test_undoes_later_receipt(self) -> None:
        seller = Seller.objects.create(user=self.user, name_seller='Shop')
        Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=seller,
            receipt_date=self.moment + timedelta(days=1),
            operation_type=1,
            total_sum=Decimal('150.00'),
        )

        self.assertEqual(
            self.service.balance_at(self.account, self.moment),
            Decimal('1150.00'),
        )

    def test_undoes_later_transaction(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Income',
            type=TransactionType.INCOME,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.INCOME,
            amount=Decimal('200.00'),
            date=self.moment + timedelta(days=1),
        )

        self.assertEqual(
            self.service.balance_at(self.account, self.moment),
            Decimal('800.00'),
        )

    def test_undoes_later_transfer_out(self) -> None:
        other_account = Account.objects.create(
            user=self.user,
            name_account='Savings',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=other_account,
            amount=Decimal('100.00'),
            exchange_date=self.moment + timedelta(days=1),
        )

        self.assertEqual(
            self.service.balance_at(self.account, self.moment),
            Decimal('1100.00'),
        )

    def test_ignores_events_on_or_before_moment(self) -> None:
        seller = Seller.objects.create(user=self.user, name_seller='Shop')
        Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=seller,
            receipt_date=self.moment - timedelta(days=1),
            operation_type=1,
            total_sum=Decimal('150.00'),
        )

        self.assertEqual(
            self.service.balance_at(self.account, self.moment),
            Decimal('1000.00'),
        )

    def test_undoes_later_deposit_withdrawal_via_registered_source(
        self,
    ) -> None:
        """Integration test: the DI-wired deposit movement source is
        consulted, not just an empty movement_sources list."""
        bank, _ = Bank.objects.get_or_create(
            code='SBERBANK',
            defaults={'name': 'Сбербанк', 'is_system': True},
        )
        deposit_account = Account.objects.create_deposit(
            user=self.user,
            name_account='Deposit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        deposit = Deposit.objects.create(
            account=deposit_account,
            name='Test deposit',
            bank=bank,
        )
        DepositPrincipalEvent.objects.create(
            deposit=deposit,
            type=DepositPrincipalEvent.Type.WITHDRAWAL,
            amount=Decimal('400.00'),
            effective_on=self.moment.date() + timedelta(days=1),
            destination_account=self.account,
        )
        service = (
            ApplicationContainer().finance_account.balance_history_service()
        )

        self.assertEqual(
            service.balance_at(self.account, self.moment),
            Decimal('600.00'),
        )
