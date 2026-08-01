from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositRatePeriod,
    DepositTerm,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


def _make_deposit(user: 'User') -> Deposit:
    account = Account.objects.create_deposit(
        user=user,
        name_account='Вклад для теста',
        bank='SBERBANK',
        currency='RUB',
        balance=Decimal('10000.00'),
    )
    return Deposit.objects.create(
        account=account,
        name='Вклад',
        bank='SBERBANK',
    )


class DepositTermRateKindTests(TestCase):
    def test_fixed_term_current_rate_falls_back_to_whole_term_period(
        self,
    ) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=100),
            is_current=True,
            rate_kind=DepositTerm.RateKind.FIXED,
        )
        DepositRatePeriod.objects.create(
            term=term,
            starts_on=term.opened_on,
            ends_on=term.matures_on,
            annual_rate=Decimal('12.00'),
        )

        self.assertTrue(term.has_defined_current_rate())
        rate = term.current_rate
        if rate is None:
            self.fail('Fixed term must always have a defined current rate.')
        self.assertEqual(rate.annual_rate, Decimal('12.00'))

    def test_floating_term_without_covering_period_has_undefined_rate(
        self,
    ) -> None:
        """A floating term whose last known period ended before today must
        report an undefined current rate, not silently reuse the last one."""
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=100),
            is_current=True,
            rate_kind=DepositTerm.RateKind.FLOATING,
        )
        DepositRatePeriod.objects.create(
            term=term,
            starts_on=term.opened_on,
            ends_on=today - timedelta(days=1),
            annual_rate=Decimal('12.00'),
        )

        self.assertFalse(term.has_defined_current_rate())
        self.assertIsNone(term.current_rate)

    def test_floating_term_with_covering_period_reports_it(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=100),
            is_current=True,
            rate_kind=DepositTerm.RateKind.FLOATING,
        )
        DepositRatePeriod.objects.create(
            term=term,
            starts_on=term.opened_on,
            ends_on=today + timedelta(days=100),
            annual_rate=Decimal('9.50'),
            note='КС ЦБ РФ + 2%',
        )

        self.assertTrue(term.has_defined_current_rate())
        rate = term.current_rate
        if rate is None:
            self.fail('Expected a covering rate period.')
        self.assertEqual(rate.annual_rate, Decimal('9.50'))
        self.assertEqual(rate.note, 'КС ЦБ РФ + 2%')
