from django.test import TestCase
from django.urls import reverse_lazy
from django.utils import timezone
from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.filters import ExpenseFilter
from hasta_la_vista_money.expense.forms import AddCategoryForm, AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User

TEST_AMOUNT = 15000
NEW_TEST_AMOUNT = 25000


class TestExpense(TestCase):
    """Test cases for Expense application."""

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
        self.expense_type = ExpenseCategory.objects.get(pk=1)
        self.parent_category = ExpenseCategory.objects.get(name='ЖКХ')

    def test_list_expense(self):
        """Test expense list view."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('expense:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_expense_create(self):
        """Test expense creation."""
        self.client.force_login(self.user)

        new_expense = {
            'user': self.user.pk,
            'account': self.account.pk,
            'category': self.expense_type.pk,
            'date': '2023-12-20T15:30',
            'amount': TEST_AMOUNT,
            'depth': 3,
        }

        form = AddExpenseForm(data=new_expense, user=self.user, depth=3)
        self.assertTrue(form.is_valid())

        url = reverse_lazy('expense:create')
        response = self.client.post(url, data=new_expense, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_expense_update(self):
        """Test expense update."""
        self.client.force_login(user=self.user)
        url = reverse_lazy('expense:change', kwargs={'pk': self.expense.pk})
        update_expense = {
            'user': self.user,
            'account': self.account.pk,
            'category': self.expense_type.pk,
            'date': '2023-06-30 22:31:54',
            'amount': NEW_TEST_AMOUNT,
            'depth': 3,
        }

        form = AddExpenseForm(data=update_expense, user=self.user, depth=3)
        self.assertTrue(form.is_valid())

        response = self.client.post(url, form.data)
        self.assertEqual(response.status_code, constants.REDIRECTS)

        updated_expense = Expense.objects.get(pk=self.expense.pk)
        self.assertEqual(updated_expense.amount, NEW_TEST_AMOUNT)

    def test_expense_delete(self):
        """Test expense deletion."""
        self.client.force_login(self.user)

        url = reverse_lazy('expense:delete', args=(self.expense.pk,))

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_category_expense_create(self):
        """Test expense category creation."""
        self.client.force_login(self.user)

        new_category = {
            'name': 'Оплата счёта',
            'parent_category': self.parent_category.pk,
        }

        form = AddCategoryForm(data=new_category, user=self.user, depth=3)
        self.assertTrue(form.is_valid())

    def test_category_expense_delete(self):
        """Test expense category deletion."""
        self.client.force_login(self.user)

        url = reverse_lazy(
            'expense:delete_category_expense',
            args=(self.expense.pk,),
        )

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_expense_model_str(self):
        """Test Expense model string representation."""
        self.assertEqual(str(self.expense), str(self.expense.category))

    def test_expense_category_model_str(self):
        """Test ExpenseCategory model string representation."""
        self.assertEqual(str(self.expense_type), self.expense_type.name)

    def test_expense_model_meta(self):
        """Test Expense model Meta configuration."""
        self.assertEqual(Expense._meta.model_name, 'expense')
        self.assertEqual(Expense._meta.app_label, 'expense')

    def test_expense_category_model_meta(self):
        """Test ExpenseCategory model Meta configuration."""
        self.assertEqual(ExpenseCategory._meta.model_name, 'expensecategory')
        self.assertEqual(ExpenseCategory._meta.app_label, 'expense')
        self.assertEqual(ExpenseCategory._meta.ordering, ['name'])

    def test_expense_category_without_parent(self):
        """Test ExpenseCategory without parent category."""
        category = ExpenseCategory.objects.create(
            user=self.user,
            name='Test Category Without Parent',
        )
        self.assertIsNone(category.parent_category)

    def test_expense_category_with_parent(self):
        """Test ExpenseCategory with parent category."""
        child_category = ExpenseCategory.objects.create(
            user=self.user,
            name='Child Category',
            parent_category=self.parent_category,
        )
        self.assertEqual(child_category.parent_category, self.parent_category)

    def test_expense_category_created_at(self):
        """Test ExpenseCategory created_at field."""
        category = ExpenseCategory.objects.create(
            user=self.user,
            name='Test Category With Created At',
        )
        self.assertIsNotNone(category.created_at)

    def test_add_expense_form_validation(self):
        """Test AddExpenseForm validation."""
        form = AddExpenseForm(
            data={
                'category': self.expense_type.pk,
                'account': self.account.pk,
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'amount': 1000,
            },
            user=self.user,
            depth=3,
        )
        self.assertTrue(form.is_valid())

    def test_add_expense_form_invalid(self):
        """Test AddExpenseForm with invalid data."""
        form = AddExpenseForm(
            data={
                'category': self.expense_type.pk,
                'amount': 'invalid_amount',
            },
            user=self.user,
            depth=3,
        )
        self.assertFalse(form.is_valid())

    def test_add_expense_form_clean_insufficient_funds(self):
        """Test AddExpenseForm clean method with insufficient funds."""
        form = AddExpenseForm(
            data={
                'category': self.expense_type.pk,
                'account': self.account.pk,
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'amount': self.account.balance + 1000,
            },
            user=self.user,
            depth=3,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('account', form.errors)

    def test_add_category_form_validation(self):
        """Test AddCategoryForm validation."""
        form = AddCategoryForm(
            data={
                'name': 'Test Category',
                'parent_category': self.parent_category.pk,
            },
            user=self.user,
            depth=3,
        )
        self.assertTrue(form.is_valid())

    def test_add_category_form_invalid(self):
        """Test AddCategoryForm with invalid data."""
        form = AddCategoryForm(
            data={
                'name': '',
            },
            user=self.user,
            depth=3,
        )
        self.assertFalse(form.is_valid())

    def test_add_category_form_without_parent(self):
        """Test AddCategoryForm without parent category."""
        form = AddCategoryForm(
            data={
                'name': 'Test Category Without Parent',
            },
            user=self.user,
            depth=3,
        )
        self.assertTrue(form.is_valid())

    def test_expense_filter(self):
        """Test ExpenseFilter functionality."""
        filter_instance = ExpenseFilter(
            data={},
            queryset=Expense.objects.all(),
            user=self.user,
        )
        self.assertIsNotNone(filter_instance.qs)

    def test_expense_filter_with_data(self):
        """Test ExpenseFilter with filter data."""
        filter_instance = ExpenseFilter(
            data={
                'category': self.expense_type.pk,
                'account': self.account.pk,
            },
            queryset=Expense.objects.all(),
            user=self.user,
        )
        self.assertIsNotNone(filter_instance.qs)

    def test_expense_filter_property_qs(self):
        """Test ExpenseFilter qs property."""
        filter_instance = ExpenseFilter(
            data={},
            queryset=Expense.objects.all(),
            user=self.user,
        )
        queryset = filter_instance.qs
        self.assertIsNotNone(queryset)
        self.assertTrue(hasattr(queryset, 'values'))

    def test_expense_filter_init(self):
        """Test ExpenseFilter initialization."""
        filter_instance = ExpenseFilter(
            data={},
            queryset=Expense.objects.all(),
            user=self.user,
        )
        self.assertEqual(filter_instance.user, self.user)

    def test_add_expense_form_configure_category_choices(self):
        """Test AddExpenseForm configure_category_choices method."""
        form = AddExpenseForm(user=self.user, depth=3)
        category_choices = [('1', 'Category 1'), ('2', 'Category 2')]
        form.configure_category_choices(category_choices)
        self.assertEqual(form.fields['category'].choices, category_choices)

    def test_add_category_form_configure_category_choices(self):
        """Test AddCategoryForm configure_category_choices method."""
        form = AddCategoryForm(user=self.user, depth=3)
        category_choices = [('1', 'Category 1'), ('2', 'Category 2')]
        form.configure_category_choices(category_choices)
        self.assertEqual(form.fields['parent_category'].choices, category_choices)

    def test_add_expense_form_field_configuration(self):
        """Test AddExpenseForm field configuration."""
        form = AddExpenseForm(user=self.user, depth=3)
        self.assertIn('category', form.fields)
        self.assertIn('account', form.fields)
        self.assertIn('date', form.fields)
        self.assertIn('amount', form.fields)

    def test_add_category_form_field_configuration(self):
        """Test AddCategoryForm field configuration."""
        form = AddCategoryForm(user=self.user, depth=3)
        self.assertIn('name', form.fields)
        self.assertIn('parent_category', form.fields)

    def test_expense_view_context_data(self):
        """Test ExpenseView context data."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('expense:list'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('expense_filter', response.context)
        self.assertIn('categories', response.context)
        self.assertIn('expenses', response.context)
        self.assertIn('add_expense_form', response.context)
        self.assertIn('flattened_categories', response.context)

    def test_expense_copy_view(self):
        """Test ExpenseCopyView functionality."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse_lazy('expense:expense_copy', args=[self.expense.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_expense_delete_view(self):
        """Test ExpenseDeleteView functionality."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse_lazy('expense:delete', args=[self.expense.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_expense_category_view(self):
        """Test ExpenseCategoryView functionality."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('expense:category_list'))
        self.assertEqual(response.status_code, 200)

    def test_expense_category_create_view_invalid_form(self):
        """Test ExpenseCategoryCreateView with invalid form."""
        self.client.force_login(self.user)
        data = {
            'name': '',
            'parent_category': self.parent_category.pk,
        }
        response = self.client.post(reverse_lazy('expense:create_category'), data)
        self.assertEqual(response.status_code, constants.REDIRECTS)

    def test_expense_category_delete_view(self):
        """Test ExpenseCategoryDeleteView functionality."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse_lazy(
                'expense:delete_category_expense',
                args=[self.expense_type.pk],
            ),
        )
        self.assertEqual(response.status_code, 302)

    def test_expense_view_unauthenticated(self):
        """Test ExpenseView for unauthenticated user."""
        response = self.client.get(reverse_lazy('expense:list'))
        self.assertEqual(response.status_code, 302)

    def test_expense_create_view_unauthenticated(self):
        """Test ExpenseCreateView for unauthenticated user."""
        response = self.client.get(reverse_lazy('expense:create'))
        self.assertEqual(response.status_code, 302)

    def test_expense_update_view_unauthenticated(self):
        """Test ExpenseUpdateView for unauthenticated user."""
        response = self.client.get(
            reverse_lazy('expense:change', args=[self.expense.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_expense_delete_view_unauthenticated(self):
        """Test ExpenseDeleteView for unauthenticated user."""
        response = self.client.post(
            reverse_lazy('expense:delete', args=[self.expense.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_expense_category_view_unauthenticated(self):
        """Test ExpenseCategoryView for unauthenticated user."""
        response = self.client.get(reverse_lazy('expense:category_list'))
        self.assertEqual(response.status_code, 302)

    def test_expense_category_create_view_unauthenticated(self):
        """Test ExpenseCategoryCreateView for unauthenticated user."""
        response = self.client.get(reverse_lazy('expense:create_category'))
        self.assertEqual(response.status_code, 302)

    def test_expense_category_delete_view_unauthenticated(self):
        """Test ExpenseCategoryDeleteView for unauthenticated user."""
        response = self.client.post(
            reverse_lazy(
                'expense:delete_category_expense',
                args=[self.expense_type.pk],
            ),
        )
        self.assertEqual(response.status_code, 302)
