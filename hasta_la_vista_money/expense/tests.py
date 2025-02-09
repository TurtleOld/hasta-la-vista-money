from django.test import TestCase
from django.urls import reverse_lazy
from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.forms import AddCategoryForm, AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User

TEST_AMOUNT = 15000
NEW_TEST_AMOUNT = 25000


class TestExpense(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'expense.yaml',
        'expense_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.expense = Expense.objects.get(pk=1)
        self.expense_type = ExpenseCategory.objects.get(pk=1)
        self.parent_category = ExpenseCategory.objects.get(name='ЖКХ')

    def test_list_expense(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('expense:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_expense_create(self):
        self.client.force_login(self.user)

        new_expense = {
            'user': self.user,
            'account': self.account,
            'category': self.expense_type,
            'date': '2023-12-20 15:30',
            'amount': TEST_AMOUNT,
            'depth': 3,
        }

        form = AddExpenseForm(data=new_expense, user=self.user, depth=3)
        self.assertTrue(form.is_valid())

    def test_expense_update(self):
        self.client.force_login(user=self.user)
        url = reverse_lazy('expense:change', kwargs={'pk': self.expense.id})
        update_expense = {
            'user': self.user,
            'account': self.account.id,
            'category': self.expense_type.id,
            'date': '2023-06-30 22:31:54',
            'amount': NEW_TEST_AMOUNT,
            'depth': 3,
        }

        form = AddExpenseForm(data=update_expense, user=self.user, depth=3)
        self.assertTrue(form.is_valid())

        response = self.client.post(url, form.data)
        self.assertEqual(response.status_code, constants.REDIRECTS)

        updated_expense = Expense.objects.get(pk=self.expense.id)
        self.assertEqual(updated_expense.amount, NEW_TEST_AMOUNT)

    def test_expense_delete(self):
        self.client.force_login(self.user)

        url = reverse_lazy('expense:delete', args=(self.expense.pk,))

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_category_expense_create(self):
        self.client.force_login(self.user)

        new_category = {
            'name': 'Оплата счёта',
            'parent_category': self.parent_category.id,
        }

        form = AddCategoryForm(data=new_category, user=self.user, depth=3)
        self.assertTrue(form.is_valid())

    def test_category_expense_delete(self):
        self.client.force_login(self.user)

        url = reverse_lazy(
            'expense:delete_category_expense',
            args=(self.expense.pk,),
        )

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
