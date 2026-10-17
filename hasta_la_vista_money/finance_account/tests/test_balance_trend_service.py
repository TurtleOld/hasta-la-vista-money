"""Balance trend: daily sums of reconstructed balances in one currency."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.db.models import F
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.deposits.commands import (
    FundDepositCommand,
    TopUpDepositCommand,
)
from hasta_la_vista_money.deposits.models import DepositTerm
from hasta_la_vista_money.finance_account.models import (
    Account,
    Bank,
    TransferMoneyLog,
)
from hasta_la_vista_money.receipts.models import Receipt, Seller
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.services.balance_trend_service import (  # noqa: E501
        BalanceTrendData,
    )
    from hasta_la_vista_money.users.models import User


def _noon(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(12)))


def _end_of_day(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.max))


def _points(trend: 'BalanceTrendData') -> dict[str, Decimal]:
    return {
        point['date']: Decimal(str(point['balance']))
        for point in trend['series']
    }


class BalanceTrendServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.today = timezone.localdate()
        container = ApplicationContainer()
        self.trend_service = container.finance_account.balance_trend_service()
        self.history = container.finance_account.balance_history_service()
        self.deposit_service = container.deposits.deposit_service()
        self.wallet = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            currency='RUB',
            balance=Decimal('1000.00'),
        )
        self.usd = Account.objects.create(
            user=self.user,
            name_account='Dollars',
            currency='USD',
            balance=Decimal('999.00'),
        )

    def _days_ago(self, days: int) -> date:
        return self.today - timedelta(days=days)

    def _fund_and_top_up_deposit(self) -> None:
        bank, _ = Bank.objects.get_or_create(
            code='SBERBANK',
            defaults={'name': 'Сбербанк', 'is_system': True},
        )
        deposit = self.deposit_service.create_funded_term_deposit(
            FundDepositCommand(
                user=self.user,
                name='Вклад',
                bank=bank,
                currency='RUB',
                amount=Decimal('500.00'),
                source_account_id=self.wallet.pk,
                opened_on=self._days_ago(20),
                matures_on=self._days_ago(-365),
                annual_rate=Decimal('10.00'),
                rate_kind=DepositTerm.RateKind.FIXED,
            ),
        )
        self.deposit_service.top_up_deposit_principal(
            TopUpDepositCommand(
                user=self.user,
                deposit_id=deposit.pk,
                source_account_id=self.wallet.pk,
                amount=Decimal('100.00'),
                effective_on=self._days_ago(10),
                exception_reason='тест',
            ),
        )

    def _spend_by_receipt(self, amount: Decimal, day: date) -> None:
        seller = Seller.objects.create(user=self.user, name_seller='Shop')
        Receipt.objects.create(
            user=self.user,
            account=self.wallet,
            seller=seller,
            receipt_date=_noon(day),
            operation_type=1,
            total_sum=amount,
        )
        Account.objects.filter(pk=self.wallet.pk).update(
            balance=F('balance') - amount,
        )

    def _transfer_to_other_user(self, amount: Decimal, day: date) -> None:
        stranger = Account.objects.create(
            user=cast('User', UserFactory()),
            name_account='Stranger',
            currency='RUB',
            balance=amount,
        )
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.wallet,
            to_account=stranger,
            amount=amount,
            exchange_date=_noon(day),
        )
        Account.objects.filter(pk=self.wallet.pk).update(
            balance=F('balance') - amount,
        )

    def _rub_accounts(self) -> list[Account]:
        return list(Account.objects.filter(user=self.user, currency='RUB'))

    def test_points_follow_receipts_transfers_and_deposit_events(
        self,
    ) -> None:
        self._fund_and_top_up_deposit()
        self._spend_by_receipt(Decimal('150.00'), self._days_ago(5))
        self._transfer_to_other_user(Decimal('50.00'), self._days_ago(3))

        trend = self.trend_service.get_balance_trend(
            Account.objects.filter(user=self.user),
            'RUB',
            '30d',
        )

        self.assertEqual(trend['current_balance'], 800.0)
        expected = {
            25: Decimal('1000.00'),
            15: Decimal('1000.00'),
            6: Decimal('1000.00'),
            5: Decimal('850.00'),
            4: Decimal('850.00'),
            3: Decimal('800.00'),
            0: Decimal('800.00'),
        }
        points = _points(trend)
        for days, balance in expected.items():
            day = self._days_ago(days)
            self.assertEqual(points[day.isoformat()], balance, msg=str(day))
            self.assertEqual(
                sum(
                    self.history.balance_at(account, _end_of_day(day))
                    for account in self._rub_accounts()
                ),
                balance,
                msg=f'balance_at sum on {day}',
            )
        self.assertEqual(trend['delta_absolute'], -200.0)

    def test_other_currency_does_not_affect_trend(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Salary',
            type=TransactionType.INCOME,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.usd,
            category=category,
            type=TransactionType.INCOME,
            amount=Decimal('999.00'),
            date=_noon(self._days_ago(3)),
        )

        trend = self.trend_service.get_balance_trend(
            Account.objects.filter(user=self.user),
            'RUB',
            '30d',
        )

        self.assertEqual(trend['current_balance'], 1000.0)
        self.assertEqual(
            {point['balance'] for point in trend['series']},
            {1000.0},
        )

    def test_query_count_does_not_depend_on_period_length(self) -> None:
        self._fund_and_top_up_deposit()
        self._spend_by_receipt(Decimal('150.00'), self._days_ago(5))
        accounts = Account.objects.filter(user=self.user)

        with self.assertNumQueries(10):
            year = self.trend_service.get_balance_trend(accounts, 'RUB', '12m')
        with self.assertNumQueries(10):
            self.trend_service.get_balance_trend(accounts, 'RUB', '7d')

        self.assertEqual(len(year['series']), 366)


class AccountListBalanceTrendCurrencyTests(TestCase):
    def test_trend_uses_selected_analytics_currency(self) -> None:
        user = cast('User', UserFactory())
        for currency, balance in (('RUB', '1000.00'), ('USD', '50.00')):
            Account.objects.create(
                user=user,
                name_account=currency,
                currency=currency,
                balance=Decimal(balance),
            )
        self.client.force_login(user)

        response = self.client.get(
            reverse('finance_account:list'),
            {'currency': 'USD'},
        )

        self.assertEqual(response.context['analytics_currency'].currency, 'USD')
        self.assertEqual(
            response.context['balance_trend']['current_balance'],
            50.0,
        )
