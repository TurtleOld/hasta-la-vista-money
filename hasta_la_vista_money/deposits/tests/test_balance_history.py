"""`balance_at` over deposit operations performed through deposit services."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.deposits.commands import (
    FundDepositCommand,
    ReverseDepositEventCommand,
    TopUpDepositCommand,
    WithdrawDepositCommand,
)
from hasta_la_vista_money.deposits.models import Deposit, DepositTerm
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


def _moment(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


class DepositBalanceHistoryTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        container = ApplicationContainer()
        self.deposit_service = container.deposits.deposit_service()
        self.history = container.finance_account.balance_history_service()
        self.source = Account.objects.create(
            user=self.user,
            name_account='Source',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        self.destination = Account.objects.create(
            user=self.user,
            name_account='Destination',
            currency='RUB',
            balance=Decimal('0.00'),
        )
        bank, _ = Bank.objects.get_or_create(
            code='SBERBANK',
            defaults={'name': 'Сбербанк', 'is_system': True},
        )
        self.deposit: Deposit = self.deposit_service.create_funded_term_deposit(
            FundDepositCommand(
                user=self.user,
                name='Вклад',
                bank=bank,
                currency='RUB',
                amount=Decimal('500.00'),
                source_account_id=self.source.pk,
                opened_on=date(2026, 1, 1),
                matures_on=date(2027, 1, 1),
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )

    def _balances(self, moment: datetime) -> tuple[Decimal, Decimal, Decimal]:
        accounts = (self.source, self.deposit.account, self.destination)
        result = []
        for account in accounts:
            account.refresh_from_db()
            result.append(self.history.balance_at(account, moment))
        return cast(
            'tuple[Decimal, Decimal, Decimal]',
            tuple(result),
        )

    def _expect(
        self,
        moment: datetime,
        source: str,
        deposit: str,
        destination: str,
    ) -> None:
        self.assertEqual(
            self._balances(moment),
            (Decimal(source), Decimal(deposit), Decimal(destination)),
            msg=f'balances at {moment}',
        )

    def test_funding_is_undone_on_both_accounts(self) -> None:
        self._expect(_moment(2025, 12, 31), '1000.00', '0.00', '0.00')
        self._expect(_moment(2026, 1, 2), '500.00', '500.00', '0.00')

    def test_top_up_is_undone_on_both_accounts(self) -> None:
        self.deposit_service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=self.user,
                deposit_id=self.deposit.pk,
                source_account_id=self.source.pk,
                amount=Decimal('100.00'),
                effective_on=date(2026, 2, 1),
                exception_reason='тест',
            ),
        )

        self._expect(_moment(2026, 1, 15), '500.00', '500.00', '0.00')
        self._expect(_moment(2026, 2, 2), '400.00', '600.00', '0.00')

    def test_withdrawal_is_undone_once(self) -> None:
        self.deposit_service.withdraw_deposit_principal(
            WithdrawDepositCommand(
                user=self.user,
                deposit_id=self.deposit.pk,
                destination_account_id=self.destination.pk,
                amount=Decimal('200.00'),
                effective_on=date(2026, 3, 10),
                exception_reason='тест',
            ),
        )

        self._expect(_moment(2026, 3, 5), '500.00', '500.00', '0.00')
        self._expect(_moment(2026, 3, 15), '500.00', '300.00', '200.00')

    def test_reversal_of_withdrawal_restores_balances(self) -> None:
        withdrawal = self.deposit_service.withdraw_deposit_principal(
            WithdrawDepositCommand(
                user=self.user,
                deposit_id=self.deposit.pk,
                destination_account_id=self.destination.pk,
                amount=Decimal('200.00'),
                effective_on=date(2026, 3, 10),
                exception_reason='тест',
            ),
        )
        self.deposit_service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=self.user,
                deposit_id=self.deposit.pk,
                event_kind='principal',
                event_id=withdrawal.pk,
                reason='Ошибка.',
                reversed_on=date(2026, 3, 20),
            ),
        )

        self._expect(_moment(2026, 3, 5), '500.00', '500.00', '0.00')
        self._expect(_moment(2026, 3, 15), '500.00', '300.00', '200.00')
        self._expect(_moment(2026, 3, 25), '500.00', '500.00', '0.00')

    def test_reversal_of_top_up_restores_balances(self) -> None:
        top_up = self.deposit_service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=self.user,
                deposit_id=self.deposit.pk,
                source_account_id=self.source.pk,
                amount=Decimal('100.00'),
                effective_on=date(2026, 2, 1),
                exception_reason='тест',
            ),
        )
        self.deposit_service.reverse_deposit_event(
            ReverseDepositEventCommand(
                user=self.user,
                deposit_id=self.deposit.pk,
                event_kind='principal',
                event_id=top_up.pk,
                reason='Ошибка.',
                reversed_on=date(2026, 2, 10),
            ),
        )

        self._expect(_moment(2026, 2, 5), '400.00', '600.00', '0.00')
        self._expect(_moment(2026, 2, 15), '500.00', '500.00', '0.00')
