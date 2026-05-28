from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.budget.models import Budget, DateList, Planning
from hasta_la_vista_money.budget.services.budget import (
    BudgetDataError,
    get_categories,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import FamilyGroupMembership

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
        self.child_expense_category = Category.objects.create(
            user=self.user,
            name='Fruit',
            type=TransactionType.EXPENSE,
            parent_category=self.expense_category,
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Salary',
            type=TransactionType.INCOME,
        )
        self.expense_categories = [self.expense_category]
        self.income_categories = [self.income_category]
        self.account = Account.objects.create(
            user=self.user,
            name_account='Main',
        )

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

    def test_aggregate_expense_table_includes_child_categories(self) -> None:
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.child_expense_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('125.00'),
            date=datetime(
                2026,
                1,
                10,
                12,
                0,
                tzinfo=timezone.get_current_timezone(),
            ),
        )

        data = self.budget_service.aggregate_expense_table(
            user=self.user,
            months=self.months,
            expense_categories=self.expense_categories,
        )

        self.assertEqual(data['expense_data'][0]['fact'][0], 125)

    def test_aggregate_expense_table_includes_family_users(self) -> None:
        member = User.objects.create_user(
            username='family_member',
            password='pass',  # nosec B106: test-only password
        )
        group = Group.objects.create(name='Budget Family')
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.user,
            role=FamilyGroupMembership.Role.OWNER,
        )
        FamilyGroupMembership.objects.create(
            group=group,
            user=member,
        )
        member_category = Category.objects.create(
            user=member,
            name='Family groceries',
            type=TransactionType.EXPENSE,
        )
        member_account = Account.objects.create(
            user=member,
            name_account='Family card',
        )
        Transaction.objects.create(
            user=member,
            account=member_account,
            category=member_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('240.00'),
            date=datetime(
                2026,
                1,
                12,
                12,
                0,
                tzinfo=timezone.get_current_timezone(),
            ),
        )
        Planning.objects.create(
            user=member,
            category=member_category,
            date=date(2026, 1, 1),
            amount=Decimal('300.00'),
            planning_type=TransactionType.EXPENSE,
        )

        data = self.budget_service.aggregate_expense_table(
            user=self.user,
            users=[self.user, member],
            months=self.months,
            expense_categories=[member_category],
        )
        family_row = data['expense_data'][0]

        self.assertEqual(
            family_row['category'],
            'family_member: Family groceries',
        )
        self.assertEqual(family_row['fact'][0], 240)
        self.assertEqual(family_row['plan'][0], 300)

    def test_aggregate_budget_limit_overview(self) -> None:
        Budget.objects.create(
            user=self.user,
            period=date(2026, 2, 1),
            amount_limit=Decimal('1000.00'),
            alert_threshold=80,
        )
        Budget.objects.create(
            user=self.user,
            period=date(2026, 2, 1),
            category=self.expense_category,
            amount_limit=Decimal('500.00'),
            alert_threshold=80,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.expense_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('450.00'),
            date=datetime(
                2026,
                2,
                10,
                12,
                0,
                tzinfo=timezone.get_current_timezone(),
            ),
        )

        overview = self.budget_service.aggregate_budget_limit_overview(
            user=self.user,
            months=self.months,
            expense_categories=self.expense_categories,
        )

        self.assertEqual(overview['current_month'], date(2026, 2, 1))
        self.assertEqual(overview['monthly_limits'][-1]['percent'], 45.0)
        self.assertEqual(overview['category_limits'][0]['status'], 'warning')

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
