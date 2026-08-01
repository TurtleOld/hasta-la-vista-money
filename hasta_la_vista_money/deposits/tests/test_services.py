from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.core.exceptions import ValidationError
from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import ACCOUNT_TYPE_DEPOSIT
from hasta_la_vista_money.deposits.commands import CreateDepositCommand
from hasta_la_vista_money.deposits.models import Deposit
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


class DepositServiceIntegrationTests(TestCase):
    def test_create_term_deposit_builds_complete_agreement(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()

        deposit = service.create_term_deposit(
            CreateDepositCommand(
                user=user,
                name='Надёжный доход',
                bank='SBERBANK',
                currency='RUB',
                balance=Decimal('150000.00'),
                opened_on=date(2026, 8, 1),
                matures_on=date(2027, 2, 1),
                annual_rate=Decimal('15.50'),
            ),
        )

        self.assertIsInstance(deposit, Deposit)
        self.assertEqual(deposit.account.user, user)
        self.assertEqual(deposit.name, 'Надёжный доход')
        self.assertEqual(deposit.bank, 'SBERBANK')
        self.assertEqual(deposit.account.user, user)
        self.assertEqual(deposit.account.type_account, ACCOUNT_TYPE_DEPOSIT)
        self.assertEqual(deposit.account.currency, 'RUB')
        self.assertEqual(deposit.account.balance, Decimal('150000.00'))

        terms = list(deposit.terms.all())
        self.assertEqual(len(terms), 1)
        term = terms[0]
        self.assertTrue(term.is_current)
        self.assertEqual(term.opened_on, date(2026, 8, 1))
        self.assertEqual(term.matures_on, date(2027, 2, 1))

        rate_periods = list(term.rate_periods.all())
        self.assertEqual(len(rate_periods), 1)
        self.assertEqual(rate_periods[0].starts_on, term.opened_on)
        self.assertEqual(rate_periods[0].ends_on, term.matures_on)
        self.assertEqual(rate_periods[0].annual_rate, Decimal('15.50'))

    def test_regular_account_creation_rejects_deposit_type(self) -> None:
        user = cast('User', UserFactory())

        with self.assertRaisesMessage(
            ValidationError,
            'Счёт вклада можно создать только через сервис вкладов.',
        ):
            Account.objects.create(
                user=user,
                name_account='Обход сервиса',
                type_account=ACCOUNT_TYPE_DEPOSIT,
                bank='SBERBANK',
                currency='RUB',
            )

        self.assertFalse(Account.objects.filter(user=user).exists())

    def test_invalid_dates_do_not_leave_partial_records(self) -> None:
        user = cast('User', UserFactory())
        service = ApplicationContainer().deposits.deposit_service()

        with self.assertRaises(ValidationError):
            service.create_term_deposit(
                CreateDepositCommand(
                    user=user,
                    name='Неверный срок',
                    bank='SBERBANK',
                    currency='RUB',
                    balance=Decimal('1000.00'),
                    opened_on=date(2027, 1, 1),
                    matures_on=date(2026, 1, 1),
                    annual_rate=Decimal('10.00'),
                ),
            )

        self.assertFalse(
            Deposit.objects.filter(account__user=user).exists(),
        )
        self.assertFalse(Account.objects.filter(user=user).exists())
