from django.db.models.query import QuerySet
from django.test import RequestFactory, TestCase
from hasta_la_vista_money.expense.forms import AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.expense.services import (
    ExpenseCategoryService,
    ExpenseService,
    ReceiptExpenseService,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class TestExpenseService(TestCase):
    """Test cases for ExpenseService."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'expense.yaml',
        'expense_cat.yaml',
    ]

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.expense = Expense.objects.get(pk=1)
        self.expense_category = ExpenseCategory.objects.get(pk=1)
        self.factory = RequestFactory()
        self.request = self.factory.get('/')
        self.service = ExpenseService(self.user, self.request)

    def test_get_categories(self) -> None:
        """Test getting expense categories."""
        categories = self.service.get_categories()
        self.assertIsInstance(categories, QuerySet)
        self.assertGreater(len(categories), 0)
        if categories:
            category = categories[0]
            self.assertIn('id', category)
            self.assertIn('name', category)
            self.assertIn('parent_category', category)

    def test_get_categories_queryset(self) -> None:
        """Test getting categories queryset."""
        queryset = self.service.get_categories_queryset()
        self.assertIsInstance(queryset, QuerySet)
        self.assertGreater(len(queryset), 0)
        for category in queryset:
            self.assertEqual(category.user, self.user)

    def test_get_form_querysets(self) -> None:
        """Test getting form querysets."""
        querysets = self.service.get_form_querysets()
        self.assertIn('category_queryset', querysets)
        self.assertIn('account_queryset', querysets)
        for account in querysets['account_queryset']:
            self.assertEqual(account.user, self.user)

    def test_get_expense_form(self) -> None:
        """Test getting expense form."""
        form = self.service.get_expense_form()
        self.assertIsInstance(form, AddExpenseForm)

    def test_create_expense(self) -> None:
        """Test creating a new expense."""
        initial_balance = self.account.balance
        form_data = {
            'account': self.account.pk,
            'category': self.expense_category.pk,
            'date': '2023-12-20T15:30',
            'amount': 1000,
        }
        form = AddExpenseForm(
            data=form_data,
            category_queryset=self.service.get_categories_queryset(),
            account_queryset=Account.objects.filter(user=self.user),
        )  # type: ignore
        self.assertTrue(form.is_valid())
        expense = self.service.create_expense(form)
        self.assertIsInstance(expense, Expense)
        self.assertEqual(expense.user, self.user)
        self.assertEqual(expense.amount, 1000)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, initial_balance - 1000)

    def test_delete_expense(self) -> None:
        """Test deleting an expense."""
        initial_balance = self.account.balance
        expense_amount = self.expense.amount
        self.service.delete_expense(self.expense)
        with self.assertRaises(Expense.DoesNotExist):
            Expense.objects.get(pk=self.expense.pk)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, initial_balance + expense_amount)

    def test_get_expenses_by_group_my(self) -> None:
        """Test getting expenses for 'my' group."""
        expenses = self.service.get_expenses_by_group('my')
        self.assertIsInstance(expenses, list)
        expense_ids = [exp.pk if hasattr(exp, 'pk') else exp['id'] for exp in expenses]
        self.assertIn(self.expense.pk, expense_ids)

    def test_get_expenses_by_group_none(self) -> None:
        """Test getting expenses for None group."""
        expenses = self.service.get_expenses_by_group(None)
        self.assertIsInstance(expenses, list)
        expense_ids = [exp.pk if hasattr(exp, 'pk') else exp['id'] for exp in expenses]
        self.assertIn(self.expense.pk, expense_ids)

    def test_get_expense_data(self) -> None:
        """Test getting expense data for AJAX."""
        data = self.service.get_expense_data('my')
        self.assertIsInstance(data, list)
        if data:
            expense_data = data[0]
            self.assertIn('id', expense_data)
            self.assertIn('date', expense_data)
            self.assertIn('amount', expense_data)
            self.assertIn('category_name', expense_data)
            self.assertIn('account_name', expense_data)
            self.assertIn('user_name', expense_data)
            self.assertIn('is_receipt', expense_data)


class TestExpenseCategoryService(TestCase):
    """Test cases for ExpenseCategoryService."""

    fixtures = [
        'users.yaml',
        'expense_cat.yaml',
    ]

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.get(pk=1)
        self.parent_category = ExpenseCategory.objects.get(name='ЖКХ')
        self.factory = RequestFactory()
        self.request = self.factory.get('/')
        self.service = ExpenseCategoryService(self.user, self.request)

    def test_get_categories(self) -> None:
        """Test getting expense categories."""
        categories = self.service.get_categories()
        self.assertIsInstance(categories, QuerySet)
        self.assertGreater(len(categories), 0)

    def test_get_categories_queryset(self) -> None:
        """Test getting categories queryset."""
        queryset = self.service.get_categories_queryset()
        self.assertIsInstance(queryset, QuerySet)
        self.assertGreater(len(queryset), 0)

    def test_create_category(self) -> None:
        """Test creating a new category."""
        from hasta_la_vista_money.expense.forms import AddCategoryForm

        form_data = {
            'name': 'Test Category',
            'parent_category': self.parent_category.pk,
        }
        form = AddCategoryForm(
            data=form_data,
            category_queryset=self.service.get_categories_queryset(),
        )  # type: ignore
        self.assertTrue(form.is_valid())
        category = self.service.create_category(form)
        self.assertIsInstance(category, ExpenseCategory)
        self.assertEqual(category.user, self.user)
        self.assertEqual(category.name, 'Test Category')


class TestReceiptExpenseService(TestCase):
    """Test cases for ReceiptExpenseService."""

    fixtures = [
        'users.yaml',
        'expense_cat.yaml',
    ]

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.get(pk=1)
        self.factory = RequestFactory()
        self.request = self.factory.get('/')
        self.service = ReceiptExpenseService(self.user, self.request)

    def test_get_receipt_expenses_no_category(self) -> None:
        """Test getting receipt expenses when category doesn't exist."""
        ExpenseCategory.objects.filter(
            user=self.user,
            name='Покупки по чекам',
        ).delete()
        expenses = self.service.get_receipt_expenses()
        self.assertEqual(expenses, [])

    def test_get_receipt_expenses_with_category(self) -> None:
        """Test getting receipt expenses when category exists."""
        receipt_category = ExpenseCategory.objects.create(
            user=self.user,
            name='Покупки по чекам',
        )
        expenses = self.service.get_receipt_expenses()
        self.assertIsInstance(expenses, list)
        receipt_category.delete()

    def test_get_receipt_expenses_by_users(self) -> None:
        """Test getting receipt expenses for multiple users."""
        users = [self.user]
        expenses = self.service.get_receipt_expenses_by_users(users)
        self.assertIsInstance(expenses, list)

    def test_get_receipt_data_by_users(self) -> None:
        """Test getting receipt data for multiple users."""
        users = [self.user]
        data = self.service.get_receipt_data_by_users(users)
        self.assertIsInstance(data, list)
