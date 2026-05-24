from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.budget.models import DateList
from hasta_la_vista_money.budget.services.budget import (
    BudgetDataError,
    get_categories,
)
from hasta_la_vista_money.transactions.models import Category, TransactionType

User = get_user_model()


class BudgetServicesTestCase(TestCase):
    """Cover the budget aggregation service end-to-end."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='budget_user',
            password='pass',  # nosec B106: test-only password
        )
        self.container = ApplicationContainer()

        self.expense_category = Category.objects.create(
            user=self.user,
            name='Groceries',
            type=TransactionType.EXPENSE,
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Salary',
            type=TransactionType.INCOME,
        )
        self.expense_categories = [self.expense_category]
        self.income_categories = [self.income_category]

        DateList.objects.create(user=self.user, date=date(2026, 1, 1))
        DateList.objects.create(user=self.user, date=date(2026, 2, 1))

        date_list_repository = self.container.budget.date_list_repository()
        self.dates = list(date_list_repository.get_by_user_ordered(self.user))
        self.months = [d.date for d in self.dates]
        self.budget_service = self.container.budget.budget_service()

    def test_get_categories_expense(self) -> None:
        cats = get_categories(self.user, 'expense')
        self.assertQuerySetEqual(
            cats.order_by('id'),
            list(self.expense_categories),
            transform=lambda x: x,
        )

    def test_get_categories_income(self) -> None:
        cats = get_categories(self.user, 'income')
        self.assertQuerySetEqual(
            cats.order_by('id'),
            list(self.income_categories),
            transform=lambda x: x,
        )

    def test_get_categories_error(self) -> None:
        with self.assertRaises(BudgetDataError):
            get_categories(None, 'expense')

    def test_aggregate_budget_data_success(self) -> None:
        data = self.budget_service.aggregate_budget_data(
            user=self.user,
            months=self.months,
            expense_categories=self.expense_categories,
            income_categories=self.income_categories,
        )
        self.assertIn('expense_data', data)
        self.assertIn('income_data', data)
        self.assertIn('chart_data', data)
        self.assertIn('chart_labels', data['chart_data'])
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_budget_data_error(self) -> None:
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_budget_data(
                None,
                self.months,
                self.expense_categories,
                self.income_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_budget_data(
                self.user,
                None,
                self.expense_categories,
                self.income_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_budget_data(
                self.user,
                self.months,
                None,
                self.income_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_budget_data(
                self.user,
                self.months,
                self.expense_categories,
                None,
            )

    def test_aggregate_budget_data_empty_months(self) -> None:
        data = self.budget_service.aggregate_budget_data(
            user=self.user,
            months=[],
            expense_categories=self.expense_categories,
            income_categories=self.income_categories,
        )
        self.assertEqual(data['months'], [])
        for row in data['expense_data']:
            self.assertEqual(row['fact'], [])
            self.assertEqual(row['plan'], [])
            self.assertEqual(row['diff'], [])
            self.assertEqual(row['percent'], [])
        for row in data['income_data']:
            self.assertEqual(row['fact'], [])
            self.assertEqual(row['plan'], [])
            self.assertEqual(row['diff'], [])
            self.assertEqual(row['percent'], [])

    def test_aggregate_budget_data_no_categories(self) -> None:
        data = self.budget_service.aggregate_budget_data(
            user=self.user,
            months=self.months,
            expense_categories=[],
            income_categories=[],
        )
        self.assertEqual(data['expense_data'], [])
        self.assertEqual(data['income_data'], [])

    def test_aggregate_expense_table_success(self) -> None:
        data = self.budget_service.aggregate_expense_table(
            user=self.user,
            months=self.months,
            expense_categories=self.expense_categories,
        )
        self.assertIn('expense_data', data)
        self.assertIn('total_fact_expense', data)
        self.assertIn('total_plan_expense', data)
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_expense_table_error(self) -> None:
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_expense_table(
                None,
                self.months,
                self.expense_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_expense_table(
                self.user,
                None,
                self.expense_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_expense_table(
                self.user,
                self.months,
                None,
            )

    def test_aggregate_expense_table_empty_months(self) -> None:
        data = self.budget_service.aggregate_expense_table(
            user=self.user,
            months=[],
            expense_categories=self.expense_categories,
        )
        self.assertEqual(data['months'], [])
        for row in data['expense_data']:
            self.assertEqual(row['fact'], [])
            self.assertEqual(row['plan'], [])
            self.assertEqual(row['diff'], [])
            self.assertEqual(row['percent'], [])

    def test_aggregate_expense_table_empty_categories(self) -> None:
        data = self.budget_service.aggregate_expense_table(
            user=self.user,
            months=self.months,
            expense_categories=[],
        )
        self.assertEqual(data['expense_data'], [])

    def test_aggregate_income_table_success(self) -> None:
        data = self.budget_service.aggregate_income_table(
            user=self.user,
            months=self.months,
            income_categories=self.income_categories,
        )
        self.assertIn('income_data', data)
        self.assertIn('total_fact_income', data)
        self.assertIn('total_plan_income', data)
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_income_table_error(self) -> None:
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_income_table(
                None,
                self.months,
                self.income_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_income_table(
                self.user,
                None,
                self.income_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_income_table(
                self.user,
                self.months,
                None,
            )

    def test_aggregate_income_table_empty_months(self) -> None:
        data = self.budget_service.aggregate_income_table(
            user=self.user,
            months=[],
            income_categories=self.income_categories,
        )
        self.assertEqual(data['months'], [])
        for row in data['income_data']:
            self.assertEqual(row['fact'], [])
            self.assertEqual(row['plan'], [])
            self.assertEqual(row['diff'], [])
            self.assertEqual(row['percent'], [])

    def test_aggregate_income_table_empty_categories(self) -> None:
        data = self.budget_service.aggregate_income_table(
            user=self.user,
            months=self.months,
            income_categories=[],
        )
        self.assertEqual(data['income_data'], [])

    def test_aggregate_expense_api_success(self) -> None:
        data = self.budget_service.aggregate_expense_api(
            user=self.user,
            months=self.months,
            expense_categories=self.expense_categories,
        )
        self.assertIn('months', data)
        self.assertIn('data', data)
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_expense_api_error(self) -> None:
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_expense_api(
                None,
                self.months,
                self.expense_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_expense_api(
                self.user,
                None,
                self.expense_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_expense_api(
                self.user,
                self.months,
                None,
            )

    def test_aggregate_expense_api_empty_months(self) -> None:
        data = self.budget_service.aggregate_expense_api(
            user=self.user,
            months=[],
            expense_categories=self.expense_categories,
        )
        self.assertEqual(data['months'], [])

    def test_aggregate_expense_api_empty_categories(self) -> None:
        data = self.budget_service.aggregate_expense_api(
            user=self.user,
            months=self.months,
            expense_categories=[],
        )
        self.assertEqual(data['data'], [])

    def test_aggregate_income_api_success(self) -> None:
        data = self.budget_service.aggregate_income_api(
            user=self.user,
            months=self.months,
            income_categories=self.income_categories,
        )
        self.assertIn('months', data)
        self.assertIn('data', data)
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_income_api_error(self) -> None:
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_income_api(
                None,
                self.months,
                self.income_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_income_api(
                self.user,
                None,
                self.income_categories,
            )
        with self.assertRaises(BudgetDataError):
            self.budget_service.aggregate_income_api(
                self.user,
                self.months,
                None,
            )

    def test_aggregate_income_api_empty_months(self) -> None:
        data = self.budget_service.aggregate_income_api(
            user=self.user,
            months=[],
            income_categories=self.income_categories,
        )
        self.assertEqual(data['months'], [])

    def test_aggregate_income_api_empty_categories(self) -> None:
        data = self.budget_service.aggregate_income_api(
            user=self.user,
            months=self.months,
            income_categories=[],
        )
        self.assertEqual(data['data'], [])
