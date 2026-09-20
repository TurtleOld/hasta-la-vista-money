"""Unit tests for DepositMovementSource translating deposit events into
FinancialMovement values for finance_account's balance facade."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.test import TestCase

from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositCapitalizationEvent,
    DepositPrincipalEvent,
)
from hasta_la_vista_money.deposits.movement_source import DepositMovementSource
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


def _sberbank() -> Bank:
    bank, _ = Bank.objects.get_or_create(
        code='SBERBANK',
        defaults={'name': 'Сбербанк', 'is_system': True},
    )
    return bank


class DepositMovementSourceTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.wallet = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        deposit_account = Account.objects.create_deposit(
            user=self.user,
            name_account='Deposit',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        self.deposit = Deposit.objects.create(
            account=deposit_account,
            name='Test deposit',
            bank=_sberbank(),
        )
        self.source = DepositMovementSource()

    def test_funding_from_account_is_a_negative_movement(self) -> None:
        DepositPrincipalEvent.objects.create(
            deposit=self.deposit,
            type=DepositPrincipalEvent.Type.FUNDING,
            amount=Decimal('500.00'),
            effective_on=date(2026, 1, 10),
            source_account=self.wallet,
        )

        movements = self.source.list_financial_movements(
            self.wallet,
            since=date(2026, 1, 1),
        )

        self.assertEqual(len(movements), 1)
        self.assertEqual(movements[0].effective_on, date(2026, 1, 10))
        self.assertEqual(movements[0].delta, Decimal('-500.00'))

    def test_withdrawal_to_account_is_a_positive_movement(self) -> None:
        DepositPrincipalEvent.objects.create(
            deposit=self.deposit,
            type=DepositPrincipalEvent.Type.WITHDRAWAL,
            amount=Decimal('300.00'),
            effective_on=date(2026, 1, 15),
            destination_account=self.wallet,
        )

        movements = self.source.list_financial_movements(
            self.wallet,
            since=date(2026, 1, 1),
        )

        self.assertEqual(len(movements), 1)
        self.assertEqual(movements[0].delta, Decimal('300.00'))

    def test_capitalization_onto_deposit_account_is_a_positive_movement(
        self,
    ) -> None:
        DepositCapitalizationEvent.objects.create(
            deposit=self.deposit,
            destination=DepositCapitalizationEvent.Destination.CAPITALIZATION,
            gross=Decimal('10.00'),
            withholding=Decimal('0.00'),
            net=Decimal('10.00'),
            posting_on=date(2026, 2, 1),
            value_on=date(2026, 2, 1),
        )

        movements = self.source.list_financial_movements(
            self.deposit.account,
            since=date(2026, 1, 1),
        )

        self.assertEqual(len(movements), 1)
        self.assertEqual(movements[0].effective_on, date(2026, 2, 1))
        self.assertEqual(movements[0].delta, Decimal('10.00'))

    def test_capitalization_paid_to_internal_account_is_a_positive_movement(
        self,
    ) -> None:
        DepositCapitalizationEvent.objects.create(
            deposit=self.deposit,
            destination=DepositCapitalizationEvent.Destination.INTERNAL_ACCOUNT,
            destination_account=self.wallet,
            gross=Decimal('20.00'),
            withholding=Decimal('2.00'),
            net=Decimal('18.00'),
            posting_on=date(2026, 2, 5),
            value_on=date(2026, 2, 5),
        )

        movements = self.source.list_financial_movements(
            self.wallet,
            since=date(2026, 1, 1),
        )

        self.assertEqual(len(movements), 1)
        self.assertEqual(movements[0].delta, Decimal('18.00'))

    def test_external_payout_has_no_balance_effect_on_any_account(
        self,
    ) -> None:
        DepositCapitalizationEvent.objects.create(
            deposit=self.deposit,
            destination=DepositCapitalizationEvent.Destination.EXTERNAL,
            gross=Decimal('15.00'),
            withholding=Decimal('0.00'),
            net=Decimal('15.00'),
            posting_on=date(2026, 2, 10),
            value_on=date(2026, 2, 10),
        )

        self.assertEqual(
            self.source.list_financial_movements(
                self.wallet,
                since=date(2026, 1, 1),
            ),
            [],
        )
        self.assertEqual(
            self.source.list_financial_movements(
                self.deposit.account,
                since=date(2026, 1, 1),
            ),
            [],
        )

    def test_movements_before_since_are_excluded(self) -> None:
        DepositPrincipalEvent.objects.create(
            deposit=self.deposit,
            type=DepositPrincipalEvent.Type.FUNDING,
            amount=Decimal('500.00'),
            effective_on=date(2026, 1, 1),
            source_account=self.wallet,
        )

        movements = self.source.list_financial_movements(
            self.wallet,
            since=date(2026, 1, 2),
        )

        self.assertEqual(movements, [])
