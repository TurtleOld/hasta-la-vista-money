from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositInterestForecast,
    DepositRatePeriod,
    DepositTerm,
)
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User


def _make_deposit(user: 'User') -> Deposit:
    bank = Bank.objects.get(code='SBERBANK')
    account = Account.objects.create_deposit(
        user=user,
        name_account='Вклад для теста',
        bank=bank,
        currency='RUB',
        balance=Decimal('10000.00'),
    )
    return Deposit.objects.create(
        account=account,
        name='Вклад',
        bank=bank,
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


class DepositTermLifecycleTests(TestCase):
    def test_liquid_amount_obeys_term_state_deadline_and_minimum(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=30),
            matures_on=today + timedelta(days=30),
            is_current=True,
            withdrawal_allowed=True,
            minimum_withdrawal_amount=Decimal('500.00'),
            withdrawal_deadline=today,
            minimum_balance=Decimal('9700.00'),
        )

        with patch(
            'hasta_la_vista_money.deposits.models.timezone.localdate',
            return_value=today,
        ):
            self.assertEqual(term.liquid_amount, Decimal())

        term.minimum_withdrawal_amount = Decimal('200.00')
        with patch(
            'hasta_la_vista_money.deposits.models.timezone.localdate',
            return_value=today,
        ):
            self.assertEqual(term.liquid_amount, Decimal('300.00'))

        with patch(
            'hasta_la_vista_money.deposits.models.timezone.localdate',
            return_value=today + timedelta(days=1),
        ):
            self.assertEqual(term.liquid_amount, Decimal())

        with patch(
            'hasta_la_vista_money.deposits.models.timezone.localdate',
            return_value=term.matures_on,
        ):
            self.assertEqual(term.liquid_amount, Decimal('10000.00'))

        term.closed_on = today
        with patch(
            'hasta_la_vista_money.deposits.models.timezone.localdate',
            return_value=today,
        ):
            self.assertEqual(term.liquid_amount, Decimal())

    def test_next_payout_is_nearest_unconfirmed_future_forecast(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=30),
            matures_on=today + timedelta(days=60),
            is_current=True,
        )
        common = {
            'term': term,
            'amount': Decimal('100.00'),
            'period_starts_on': today - timedelta(days=30),
            'period_ends_on': today,
        }
        DepositInterestForecast.objects.create(
            **common,
            payout_on=today - timedelta(days=1),
        )
        DepositInterestForecast.objects.create(
            **common,
            payout_on=today + timedelta(days=10),
            confirmed=True,
        )
        expected = DepositInterestForecast.objects.create(
            **common,
            payout_on=today + timedelta(days=20),
        )

        with patch(
            'hasta_la_vista_money.deposits.models.timezone.localdate',
            return_value=today,
        ):
            self.assertEqual(term.next_payout, expected)

    def test_term_is_matured_on_planned_maturity_date(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=30),
            matures_on=today,
            is_current=True,
        )

        with patch(
            'hasta_la_vista_money.deposits.models.timezone.localdate',
            return_value=today,
        ):
            self.assertEqual(term.state, DepositTerm.State.MATURED)

        deposit.account.refresh_from_db()
        self.assertEqual(deposit.account.balance, Decimal('10000.00'))
        self.assertFalse(deposit.capitalization_events.exists())

    def test_accrual_date_falls_back_to_opened_on_when_null(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=100),
            is_current=True,
            interest_accrual_starts_on=None,
        )
        self.assertEqual(term.accrual_date, term.opened_on)

    def test_accrual_date_differs_from_opened_on_when_set(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        accrual_start = today - timedelta(days=5)
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=100),
            is_current=True,
            interest_accrual_starts_on=accrual_start,
        )
        self.assertNotEqual(term.accrual_date, term.opened_on)
        self.assertEqual(term.accrual_date, accrual_start)


class DepositTermMoneyPrecisionTests(TestCase):
    def test_rub_has_kopek_precision(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        deposit.account.currency = 'RUB'
        deposit.account.save()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=100),
            is_current=True,
        )
        self.assertEqual(term.money_precision, Decimal('0.01'))

    def test_jpy_has_integer_precision(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        deposit.account.currency = 'JPY'
        deposit.account.save()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=100),
            is_current=True,
        )
        self.assertEqual(term.money_precision, Decimal(1))

    def test_bhd_has_milli_precision(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        deposit.account.currency = 'BHD'
        deposit.account.save()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=100),
            is_current=True,
        )
        self.assertEqual(term.money_precision, Decimal('0.001'))

    def test_unknown_currency_defaults_to_kopek_precision(self) -> None:
        user = cast('User', UserFactory())
        deposit = _make_deposit(user)
        today = timezone.localdate()
        deposit.account.currency = 'XYZ'
        deposit.account.save()
        term = DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today - timedelta(days=10),
            matures_on=today + timedelta(days=100),
            is_current=True,
        )
        self.assertEqual(term.money_precision, Decimal('0.01'))
