"""Tests for finance account prepare functions."""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.prepare import (
    collect_info_expense,
    collect_info_income,
    sort_expense_income,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


class TestPrepareFunctions(TestCase):
    """Test cases for prepare module functions."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',  # nosec B106: test-only password
        )

        self.account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

        self.expense_category = Category.objects.create(
            name='Test Expense Category',
            user=self.user,
            type=TransactionType.EXPENSE,
        )

        self.income_category = Category.objects.create(
            name='Test Income Category',
            user=self.user,
            type=TransactionType.INCOME,
        )

    def test_collect_info_expense_with_data(self) -> None:
        """Test collect_info_expense with expense data."""
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('100.00'),
            date=timezone.now().date(),
        )

        expense_info = collect_info_expense(self.user)

        self.assertIsNotNone(expense_info)
        self.assertIsInstance(expense_info, list)

    def test_collect_info_expense_empty(self) -> None:
        """Test collect_info_expense with no expense data."""
        expense_info = collect_info_expense(self.user)

        self.assertIsNotNone(expense_info)
        self.assertIsInstance(expense_info, list)

    def test_collect_info_expense_multiple_expenses(self) -> None:
        """Test collect_info_expense with multiple expenses."""
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('100.00'),
            date=timezone.now().date(),
        )
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('200.00'),
            date=timezone.now().date(),
        )

        expense_info = collect_info_expense(self.user)

        self.assertIsNotNone(expense_info)
        self.assertIsInstance(expense_info, list)

    def test_collect_info_expense_different_dates(self) -> None:
        """Test collect_info_expense with expenses on different dates."""
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('100.00'),
            date=timezone.now().date(),
        )
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('200.00'),
            date=timezone.now().date().replace(day=1),
        )

        expense_info = collect_info_expense(self.user)

        self.assertIsNotNone(expense_info)
        self.assertIsInstance(expense_info, list)

    def test_collect_info_income_with_data(self) -> None:
        """Test collect_info_income with income data."""
        Transaction.objects.create(
            type=TransactionType.INCOME,
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1000.00'),
            date=timezone.now().date(),
        )

        income_info = collect_info_income(self.user)

        self.assertIsNotNone(income_info)
        self.assertIsInstance(income_info, list)

    def test_collect_info_income_empty(self) -> None:
        """Test collect_info_income with no income data."""
        income_info = collect_info_income(self.user)

        self.assertIsNotNone(income_info)
        self.assertIsInstance(income_info, list)

    def test_collect_info_income_multiple_incomes(self) -> None:
        """Test collect_info_income with multiple incomes."""
        Transaction.objects.create(
            type=TransactionType.INCOME,
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1000.00'),
            date=timezone.now().date(),
        )
        Transaction.objects.create(
            type=TransactionType.INCOME,
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('2000.00'),
            date=timezone.now().date(),
        )

        income_info = collect_info_income(self.user)

        self.assertIsNotNone(income_info)
        self.assertIsInstance(income_info, list)

    def test_collect_info_income_different_dates(self) -> None:
        """Test collect_info_income with incomes on different dates."""
        Transaction.objects.create(
            type=TransactionType.INCOME,
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1000.00'),
            date=timezone.now().date(),
        )
        Transaction.objects.create(
            type=TransactionType.INCOME,
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('2000.00'),
            date=timezone.now().date().replace(day=1),
        )

        income_info = collect_info_income(self.user)

        self.assertIsNotNone(income_info)
        self.assertIsInstance(income_info, list)

    def test_sort_expense_income_with_data(self) -> None:
        """Test sort_expense_income with expense and income data."""
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('100.00'),
            date=timezone.now().date(),
        )

        Transaction.objects.create(
            type=TransactionType.INCOME,
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1000.00'),
            date=timezone.now().date(),
        )

        expense_info = collect_info_expense(self.user)
        income_info = collect_info_income(self.user)

        sorted_data = sort_expense_income(expense_info, income_info)

        self.assertIsNotNone(sorted_data)
        self.assertIsInstance(sorted_data, list)

    def test_sort_expense_income_empty_data(self) -> None:
        """Test sort_expense_income with empty data."""
        expense_info = collect_info_expense(self.user)
        income_info = collect_info_income(self.user)

        sorted_data = sort_expense_income(expense_info, income_info)

        self.assertIsNotNone(sorted_data)
        self.assertIsInstance(sorted_data, list)

    def test_sort_expense_income_only_expenses(self) -> None:
        """Test sort_expense_income with only expense data."""
        Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('100.00'),
            date=timezone.now().date(),
        )

        expense_info = collect_info_expense(self.user)
        income_info = collect_info_income(self.user)

        sorted_data = sort_expense_income(expense_info, income_info)

        self.assertIsNotNone(sorted_data)
        self.assertIsInstance(sorted_data, list)

    def test_sort_expense_income_only_incomes(self) -> None:
        """Test sort_expense_income with only income data."""
        Transaction.objects.create(
            type=TransactionType.INCOME,
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1000.00'),
            date=timezone.now().date(),
        )

        expense_info = collect_info_expense(self.user)
        income_info = collect_info_income(self.user)

        sorted_data = sort_expense_income(expense_info, income_info)

        self.assertIsNotNone(sorted_data)
        self.assertIsInstance(sorted_data, list)

    def test_sort_expense_income_multiple_records(self) -> None:
        """Test sort_expense_income with multiple expense and income records."""
        for _ in range(5):
            Transaction.objects.create(
                type=TransactionType.EXPENSE,
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('100.00'),
                date=timezone.now().date(),
            )

            Transaction.objects.create(
                type=TransactionType.INCOME,
                user=self.user,
                account=self.account,
                category=self.income_category,
                amount=Decimal('1000.00'),
                date=timezone.now().date(),
            )

        expense_info = collect_info_expense(self.user)
        income_info = collect_info_income(self.user)

        sorted_data = sort_expense_income(expense_info, income_info)

        self.assertIsNotNone(sorted_data)
        self.assertIsInstance(sorted_data, list)

    def test_sort_expense_income_none_inputs(self) -> None:
        """Test sort_expense_income with None inputs."""
        sorted_data = sort_expense_income(None, None)

        self.assertIsNotNone(sorted_data)
        self.assertIsInstance(sorted_data, list)

    def test_sort_expense_income_empty_dict_inputs(self) -> None:
        """Test sort_expense_income with empty dict inputs."""
        sorted_data = sort_expense_income([], [])

        self.assertIsNotNone(sorted_data)
        self.assertIsInstance(sorted_data, list)
