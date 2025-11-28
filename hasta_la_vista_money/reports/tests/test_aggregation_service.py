from datetime import date
from typing import ClassVar

from django.test import TestCase

from hasta_la_vista_money.budget.models import DateList
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.reports.services.aggregation import (
    budget_charts,
    collect_datasets,
    pie_expense_category,
    transform_dataset,
    unique_aggregate,
)
from hasta_la_vista_money.users.models import User


class AggregationPureFunctionsTests(TestCase):
    def test_transform_dataset(self) -> None:
        dataset = [
            {
                'date': __import__('datetime').date(2025, 1, 1),
                'total_amount': 10,
            },
            {
                'date': __import__('datetime').date(2025, 1, 2),
                'total_amount': 5.5,
            },
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
    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
        'expense_cat.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)

    def test_collect_datasets(self) -> None:
        expense_dataset, income_dataset = collect_datasets(self.user)
        self.assertIsNotNone(expense_dataset)
        self.assertIsNotNone(income_dataset)


class PieExpenseCategoryTest(TestCase):
    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
        'expense_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)

    def test_pie_expense_category(self) -> None:
        charts = pie_expense_category(self.user)
        self.assertIsInstance(charts, list)


class BudgetChartsTest(TestCase):
    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
        'expense_cat.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        DateList.objects.create(user=self.user, date=date(2025, 1, 1))

    def test_budget_charts(self) -> None:
        charts_data = budget_charts(self.user)
        self.assertIsInstance(charts_data, dict)
        self.assertIn('chart_labels', charts_data)
        self.assertIn('chart_income', charts_data)
        self.assertIn('chart_expense', charts_data)
        self.assertIn('chart_balance', charts_data)
        self.assertIn('pie_labels', charts_data)
        self.assertIn('pie_values', charts_data)
