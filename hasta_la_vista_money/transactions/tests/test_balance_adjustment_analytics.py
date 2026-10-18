"""Balance adjustments stay out of analytics but move the balance."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.budget.models import DateList
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services.balance_history_service import (  # noqa: E501
    BalanceHistoryService,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    SystemCategoryKind,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.services.dashboard_kpis import (
    get_dashboard_month_kpis,
)
from hasta_la_vista_money.users.services.forecast import (
    build_cashflow_forecast,
)

User = get_user_model()


class BalanceAdjustmentAnalyticsTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='adjust-user')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Main',
            balance=Decimal('1000.00'),
        )
        self.now = timezone.now()
        self.food = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        adjustment = {
            category.type: category
            for category in Category.objects.filter(
                user=self.user,
                system_kind=SystemCategoryKind.BALANCE_ADJUSTMENT,
            )
        }
        self.adjustment_expense = adjustment[TransactionType.EXPENSE]
        self.adjustment_income = adjustment[TransactionType.INCOME]
        self.spend(self.food, TransactionType.EXPENSE, '100.00')
        self.spend(self.adjustment_expense, TransactionType.EXPENSE, '70.00')
        self.spend(self.adjustment_income, TransactionType.INCOME, '30.00')

    def spend(self, category: Category, type_value: str, amount: str) -> None:
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=type_value,
            amount=Decimal(amount),
            date=self.now,
        )

    def test_dashboard_kpis_ignore_adjustments(self) -> None:
        kpis = get_dashboard_month_kpis(self.user, currency='RUB')

        self.assertEqual(kpis['income'], Decimal(0))
        self.assertEqual(kpis['expenses'], Decimal(100))

    def test_statistics_sums_ignore_adjustments(self) -> None:
        repository = StatisticsRepository()
        start = self.now - timedelta(days=1)

        self.assertEqual(
            repository.get_expenses_sum_by_period(self.user, 'RUB', start),
            Decimal('100.00'),
        )
        self.assertEqual(
            repository.get_income_sum_by_period(self.user, 'RUB', start),
            Decimal(0),
        )

    def test_budget_fact_ignores_adjustments(self) -> None:
        month = self.now.date().replace(day=1)
        DateList.objects.create(user=self.user, date=month)
        container = ApplicationContainer()
        date_lists = container.budget.date_list_repository()
        months = [row.date for row in date_lists.get_by_user_ordered(self.user)]

        data = container.budget.budget_service().aggregate_expense_table(
            user=self.user,
            months=months,
            expense_categories=[self.food, self.adjustment_expense],
            currency='RUB',
        )

        facts = {
            row['category']: row['fact'][0] for row in data['expense_data']
        }
        self.assertEqual(facts['Food'], Decimal('100.00'))
        self.assertEqual(facts[self.adjustment_expense.name], Decimal(0))

    def test_forecast_ignores_adjustments(self) -> None:
        Transaction.objects.filter(category=self.food).delete()

        forecast = build_cashflow_forecast(
            users=[self.user],
            accounts=[self.account],
            today=self.now.date(),
            currency='RUB',
        )

        self.assertEqual(
            set(forecast['forecast_balance']),
            {float(self.account.balance)},
        )

    def test_balance_history_and_feed_keep_adjustments(self) -> None:
        moment = self.now - timedelta(days=1)

        balance = BalanceHistoryService(movement_sources=[]).balance_at(
            self.account,
            moment,
        )

        # 1000 now, undo +30 income, +70 expense and +100 expense after moment
        self.assertEqual(balance, Decimal('1140.00'))
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 3)
