from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from hasta_la_vista_money.budget.models import DateList
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.reports.services.aggregation import (
    budget_charts,
    collect_datasets,
    pie_expense_category,
    transform_dataset,
    unique_aggregate,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)

User = get_user_model()


class AggregationPureFunctionsTests(TestCase):
    def test_transform_dataset(self) -> None:
        dataset = [
            {'date': date(2025, 1, 1), 'total_amount': 10},
            {'date': date(2025, 1, 2), 'total_amount': 5.5},
        ]
        dates, amounts = transform_dataset(dataset)
        self.assertEqual(dates, ['2025-01-01', '2025-01-02'])
        self.assertEqual(amounts, [10.0, 5.5])

    def test_transform_dataset_string_date(self) -> None:
        dataset = [
            {'date': '2025-01-01', 'total_amount': 10},
        ]
        dates, amounts = transform_dataset(dataset)
        self.assertEqual(len(dates), 1)
        self.assertEqual(amounts, [10.0])

    def test_unique_aggregate(self) -> None:
        dates = ['2025-01-01', '2025-01-01', '2025-01-02']
        amounts = [10.0, 5.0, 3.0]
        u_dates, u_amounts = unique_aggregate(dates, amounts)
        self.assertEqual(u_dates, ['2025-01-01', '2025-01-02'])
        self.assertEqual(u_amounts, [15.0, 3.0])

    def test_unique_aggregate_empty(self) -> None:
        dates: list[str] = []
        amounts: list[float] = []
        u_dates, u_amounts = unique_aggregate(dates, amounts)
        self.assertEqual(u_dates, [])
        self.assertEqual(u_amounts, [])


class CollectDatasetsTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='reports_user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Checking',
            balance=Decimal('1000.00'),
        )

    def test_collect_datasets(self) -> None:
        expense_dataset, income_dataset = collect_datasets(self.user)
        self.assertIsNotNone(expense_dataset)
        self.assertIsNotNone(income_dataset)


class PieExpenseCategoryTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='reports_user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Checking',
            balance=Decimal('1000.00'),
        )

    def test_pie_expense_category(self) -> None:
        charts = pie_expense_category(self.user)
        self.assertIsInstance(charts, list)

    def test_pie_expense_category_groups_monthly_parent_totals(self) -> None:
        parent_category = Category.objects.create(
            user=self.user,
            name='Food Parent',
            type=TransactionType.EXPENSE,
        )
        groceries_category = Category.objects.create(
            user=self.user,
            name='Groceries',
            type=TransactionType.EXPENSE,
            parent_category=parent_category,
        )
        cafe_category = Category.objects.create(
            user=self.user,
            name='Cafe',
            type=TransactionType.EXPENSE,
            parent_category=parent_category,
        )

        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=groceries_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('120.00'),
            date=datetime(
                2026,
                1,
                5,
                tzinfo=timezone.get_current_timezone(),
            ),
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=cafe_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('80.00'),
            date=datetime(
                2026,
                1,
                8,
                tzinfo=timezone.get_current_timezone(),
            ),
        )

        charts = pie_expense_category(self.user)

        food_chart = next(
            chart
            for chart in charts
            if chart['parent_category'] == 'Food Parent'
        )
        self.assertEqual(len(food_chart['data']), 1)
        self.assertEqual(food_chart['data'][0]['y'], 200.0)
        self.assertEqual(len(food_chart['drilldown_series']), 1)
        self.assertEqual(
            {
                item['name']
                for item in food_chart['drilldown_series'][0]['data']
            },
            {'Groceries', 'Cafe'},
        )


class BudgetChartsTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='reports_user',
            password='pass',  # nosec B106: test-only password
        )
        DateList.objects.create(user=self.user, date=date(2025, 1, 1))
        cache.clear()

    def test_budget_charts(self) -> None:
        charts_data = budget_charts(self.user)
        self.assertIsInstance(charts_data, dict)
        self.assertIn('chart_labels', charts_data)
        self.assertIn('chart_income', charts_data)
        self.assertIn('chart_expense', charts_data)
        self.assertIn('chart_balance', charts_data)
        self.assertIn('pie_labels', charts_data)
        self.assertIn('pie_values', charts_data)

    def test_budget_charts_uses_cache(self) -> None:
        budget_charts(self.user)

        with CaptureQueriesContext(connection) as queries:
            charts_data = budget_charts(self.user)

        self.assertIn('chart_labels', charts_data)
        self.assertEqual(len(queries), 0)
