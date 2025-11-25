from typing import ClassVar

from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.budget.services.budget import (
    BudgetDataError,
    aggregate_budget_data,
    aggregate_expense_api,
    aggregate_expense_table,
    aggregate_income_api,
    aggregate_income_table,
    get_categories,
)
from hasta_la_vista_money.users.models import User


class BudgetServicesTestCase(TestCase):
    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'expense_cat.yaml',
        'income_cat.yaml',
        'expense.yaml',
        'income.yaml',
        'finance_account.yaml',
        'loan.yaml',
        'receipt_product.yaml',
        'receipt_receipt.yaml',
        'receipt_seller.yaml',
    ]

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            raise ValueError('No user found in fixtures')
        self.user = user
        self.container = ApplicationContainer()
        self.expense_categories = list(
            self.user.category_expense_users.filter(
                parent_category=None,
            ),
        )
        self.income_categories = list(
            self.user.category_income_users.filter(
                parent_category=None,
            ),
        )
        date_list_repository = self.container.budget.date_list_repository()
        self.dates = list(date_list_repository.get_by_user_ordered(self.user))
        self.months = [d.date for d in self.dates]

    def test_get_categories_expense(self) -> None:
        """Test get_categories returns expense categories for user."""
        cats = get_categories(self.user, 'expense')
        self.assertQuerySetEqual(
            cats.order_by('id'),
            list(self.expense_categories),
            transform=lambda x: x,
        )

    def test_get_categories_income(self) -> None:
        """Test get_categories returns income categories for user."""
        cats = get_categories(self.user, 'income')
        self.assertQuerySetEqual(
            cats.order_by('id'),
            list(self.income_categories),
            transform=lambda x: x,
        )

    def test_get_categories_error(self) -> None:
        """Test get_categories raises error if user is None."""
        with self.assertRaises(BudgetDataError):
            get_categories(None, 'expense')

    def test_aggregate_budget_data_success(self) -> None:
        """Test aggregate_budget_data returns correct structure."""
        data = aggregate_budget_data(
            user=self.user,
            months=self.months,
            expense_categories=self.expense_categories,
            income_categories=self.income_categories,
            container=self.container,
        )
        self.assertIn('expense_data', data)
        self.assertIn('income_data', data)
        self.assertIn('chart_data', data)
        self.assertIn('chart_labels', data['chart_data'])
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_budget_data_error(self) -> None:
        """Test aggregate_budget_data raises error on missing data."""
        with self.assertRaises(BudgetDataError):
            aggregate_budget_data(
                None,  # type: ignore[arg-type]
                self.months,
                self.expense_categories,
                self.income_categories,
                self.container,
            )
        with self.assertRaises(BudgetDataError):
            aggregate_budget_data(
                self.user,
                None,  # type: ignore[arg-type]
                self.expense_categories,
                self.income_categories,
                self.container,
            )
        with self.assertRaises(BudgetDataError):
            aggregate_budget_data(
                self.user,
                self.months,
                None,  # type: ignore[arg-type]
                self.income_categories,
                self.container,
            )
        with self.assertRaises(BudgetDataError):
            aggregate_budget_data(
                self.user,
                self.months,
                self.expense_categories,
                None,  # type: ignore[arg-type]
                self.container,
            )

    def test_aggregate_budget_data_empty_months(self) -> None:
        """Test aggregate_budget_data with empty months list."""
        data = aggregate_budget_data(
            user=self.user,
            months=[],
            expense_categories=self.expense_categories,
            income_categories=self.income_categories,
            container=self.container,
        )
        self.assertEqual(data['months'], [])
        # Проверяем, что для каждой категории массивы пустые
        for row in data['expense_data']:
            self.assertEqual(row['fact'], [])
            self.assertEqual(row['plan'], [])
            self.assertEqual(row['diff'], [])
            self.assertEqual(row['percent'], [])
        for row in data['income_data']:  # type: ignore[assignment]
            self.assertEqual(row['fact'], [])
            self.assertEqual(row['plan'], [])
            self.assertEqual(row['diff'], [])
            self.assertEqual(row['percent'], [])

    def test_aggregate_budget_data_no_categories(self) -> None:
        """Test aggregate_budget_data with no categories."""
        data = aggregate_budget_data(
            user=self.user,
            months=self.months,
            expense_categories=[],
            income_categories=[],
            container=self.container,
        )
        self.assertEqual(data['expense_data'], [])
        self.assertEqual(data['income_data'], [])

    def test_aggregate_expense_table_success(self) -> None:
        """Test aggregate_expense_table returns correct structure."""
        data = aggregate_expense_table(
            user=self.user,
            months=self.months,
            expense_categories=self.expense_categories,
            container=self.container,
        )
        self.assertIn('expense_data', data)
        self.assertIn('total_fact_expense', data)
        self.assertIn('total_plan_expense', data)
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_expense_table_error(self) -> None:
        """Test aggregate_expense_table raises error on missing data."""
        with self.assertRaises(BudgetDataError):
            aggregate_expense_table(
                None,
                self.months,
                self.expense_categories,
                self.container,
            )  # type: ignore[arg-type]
        with self.assertRaises(BudgetDataError):
            aggregate_expense_table(
                self.user,
                None,
                self.expense_categories,
                self.container,
            )  # type: ignore[arg-type]
        with self.assertRaises(BudgetDataError):
            aggregate_expense_table(
                self.user,
                self.months,
                None,
                self.container,
            )  # type: ignore[arg-type]

    def test_aggregate_expense_table_empty_months(self) -> None:
        data = aggregate_expense_table(
            user=self.user,
            months=[],
            expense_categories=self.expense_categories,
            container=self.container,
        )
        self.assertEqual(data['months'], [])
        for row in data['expense_data']:
            self.assertEqual(row['fact'], [])
            self.assertEqual(row['plan'], [])
            self.assertEqual(row['diff'], [])
            self.assertEqual(row['percent'], [])

    def test_aggregate_expense_table_empty_categories(self) -> None:
        data = aggregate_expense_table(
            user=self.user,
            months=self.months,
            expense_categories=[],
            container=self.container,
        )
        self.assertEqual(data['expense_data'], [])

    def test_aggregate_income_table_success(self) -> None:
        """Test aggregate_income_table returns correct structure."""
        data = aggregate_income_table(
            user=self.user,
            months=self.months,
            income_categories=self.income_categories,
            container=self.container,
        )
        self.assertIn('income_data', data)
        self.assertIn('total_fact_income', data)
        self.assertIn('total_plan_income', data)
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_income_table_error(self) -> None:
        """Test aggregate_income_table raises error on missing data."""
        with self.assertRaises(BudgetDataError):
            aggregate_income_table(
                None,
                self.months,
                self.income_categories,
                self.container,
            )  # type: ignore[arg-type]
        with self.assertRaises(BudgetDataError):
            aggregate_income_table(
                self.user,
                None,
                self.income_categories,
                self.container,
            )  # type: ignore[arg-type]
        with self.assertRaises(BudgetDataError):
            aggregate_income_table(
                self.user,
                self.months,
                None,
                self.container,
            )  # type: ignore[arg-type]

    def test_aggregate_income_table_empty_months(self) -> None:
        data = aggregate_income_table(
            user=self.user,
            months=[],
            income_categories=self.income_categories,
            container=self.container,
        )
        self.assertEqual(data['months'], [])
        for row in data['income_data']:
            self.assertEqual(row['fact'], [])
            self.assertEqual(row['plan'], [])
            self.assertEqual(row['diff'], [])
            self.assertEqual(row['percent'], [])

    def test_aggregate_income_table_empty_categories(self) -> None:
        data = aggregate_income_table(
            user=self.user,
            months=self.months,
            income_categories=[],
            container=self.container,
        )
        self.assertEqual(data['income_data'], [])

    def test_aggregate_expense_api_success(self) -> None:
        """Test aggregate_expense_api returns correct structure."""
        data = aggregate_expense_api(
            user=self.user,
            months=self.months,
            expense_categories=self.expense_categories,
            container=self.container,
        )
        self.assertIn('months', data)
        self.assertIn('data', data)
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_expense_api_error(self) -> None:
        """Test aggregate_expense_api raises error on missing data."""
        with self.assertRaises(BudgetDataError):
            aggregate_expense_api(
                None,
                self.months,
                self.expense_categories,
                self.container,
            )  # type: ignore[arg-type]
        with self.assertRaises(BudgetDataError):
            aggregate_expense_api(
                self.user,
                None,
                self.expense_categories,
                self.container,
            )  # type: ignore[arg-type]
        with self.assertRaises(BudgetDataError):
            aggregate_expense_api(
                self.user,
                self.months,
                None,
                self.container,
            )  # type: ignore[arg-type]

    def test_aggregate_expense_api_empty_months(self) -> None:
        data = aggregate_expense_api(
            user=self.user,
            months=[],
            expense_categories=self.expense_categories,
            container=self.container,
        )
        self.assertEqual(data['months'], [])
        for row in data['data']:
            self.assertTrue(
                all(
                    row[f] == []  # type: ignore[literal-required]
                    for f in ['fact_' + str(m) for m in data['months']]
                ),
            )

    def test_aggregate_expense_api_empty_categories(self) -> None:
        data = aggregate_expense_api(
            user=self.user,
            months=self.months,
            expense_categories=[],
            container=self.container,
        )
        self.assertEqual(data['data'], [])

    def test_aggregate_income_api_success(self) -> None:
        """Test aggregate_income_api returns correct structure."""
        data = aggregate_income_api(
            user=self.user,
            months=self.months,
            income_categories=self.income_categories,
            container=self.container,
        )
        self.assertIn('months', data)
        self.assertIn('data', data)
        self.assertEqual(len(data['months']), len(self.months))

    def test_aggregate_income_api_error(self) -> None:
        """Test aggregate_income_api raises error on missing data."""
        with self.assertRaises(BudgetDataError):
            aggregate_income_api(
                None,
                self.months,
                self.income_categories,
                self.container,
            )  # type: ignore[arg-type]
        with self.assertRaises(BudgetDataError):
            aggregate_income_api(
                self.user,
                None,
                self.income_categories,
                self.container,
            )  # type: ignore[arg-type]
        with self.assertRaises(BudgetDataError):
            aggregate_income_api(
                self.user,
                self.months,
                None,
                self.container,
            )  # type: ignore[arg-type]

    def test_aggregate_income_api_empty_months(self) -> None:
        data = aggregate_income_api(
            user=self.user,
            months=[],
            income_categories=self.income_categories,
            container=self.container,
        )
        self.assertEqual(data['months'], [])
        for row in data['data']:
            self.assertTrue(
                all(
                    row[f] == []  # type: ignore[literal-required]
                    for f in ['fact_' + str(m) for m in data['months']]
                ),
            )

    def test_aggregate_income_api_empty_categories(self) -> None:
        data = aggregate_income_api(
            user=self.user,
            months=self.months,
            income_categories=[],
            container=self.container,
        )
        self.assertEqual(data['data'], [])
