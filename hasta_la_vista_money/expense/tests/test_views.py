from django.test import TestCase
from typing import ClassVar
from django.urls import reverse_lazy

from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User

TEST_AMOUNT = 15000
NEW_TEST_AMOUNT = 25000


class TestExpenseViews(TestCase):
    fixtures: ClassVar[list[str]] = [
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
            'account': self.account.pk,
            'category': self.expense_type.pk,
            'date': '2023-12-20T15:30',
            'amount': TEST_AMOUNT,
        }
        url = reverse_lazy('expense:create')
        response = self.client.post(url, data=new_expense, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_expense_update(self):
        self.client.force_login(self.user)
        url = reverse_lazy('expense:change', kwargs={'pk': self.expense.pk})
        update_expense = {
            'account': self.account.pk,
            'category': self.expense_type.pk,
            'date': '2023-06-30T22:31',
            'amount': NEW_TEST_AMOUNT,
        }
        response = self.client.post(url, update_expense)
        self.assertIn(response.status_code, [constants.REDIRECTS, 302])
        updated_expense = Expense.objects.get(pk=self.expense.pk)
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
            'parent_category': self.parent_category.pk,
        }
        url = reverse_lazy('expense:create_category')
        response = self.client.post(url, data=new_category, follow=True)
        self.assertIn(response.status_code, [constants.SUCCESS_CODE, 302])

    def test_category_expense_delete(self):
        self.client.force_login(self.user)
        url = reverse_lazy(
            'expense:delete_category_expense',
            args=(self.expense.pk,),
        )
        response = self.client.post(url, follow=True)
        self.assertIn(response.status_code, [constants.SUCCESS_CODE, 302])

    def test_expense_copy_view(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse_lazy('expense:expense_copy', args=[self.expense.pk]),
        )
        self.assertIn(response.status_code, [302, constants.REDIRECTS])

    def test_expense_delete_view(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse_lazy('expense:delete', args=[self.expense.pk]),
        )
        self.assertIn(response.status_code, [302, constants.REDIRECTS])

    def test_expense_category_view(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('expense:category_list'))
        self.assertEqual(response.status_code, 200)

    def test_expense_category_create_view_invalid_form(self):
        self.client.force_login(self.user)
        data = {
            'name': '',
            'parent_category': self.parent_category.pk,
        }
        response = self.client.post(
            reverse_lazy('expense:create_category'),
            data,
        )
        self.assertIn(response.status_code, [constants.SUCCESS_CODE, 200])

    def test_expense_category_delete_view(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse_lazy(
                'expense:delete_category_expense',
                args=[self.expense_type.pk],
            ),
        )
        self.assertIn(response.status_code, [302, constants.REDIRECTS])

    def test_expense_view_unauthenticated(self):
        response = self.client.get(reverse_lazy('expense:list'))
        self.assertIn(response.status_code, [302, constants.REDIRECTS])

    def test_expense_create_view_unauthenticated(self):
        data = {
            'account': self.account.pk,
            'category': self.expense_type.pk,
            'date': '2023-12-20T15:30',
            'amount': TEST_AMOUNT,
        }
        response = self.client.post(reverse_lazy('expense:create'), data)
        self.assertIn(response.status_code, [302, constants.REDIRECTS])

    def test_expense_update_view_unauthenticated(self):
        data = {
            'account': self.account.pk,
            'category': self.expense_type.pk,
            'date': '2023-06-30T22:31',
            'amount': NEW_TEST_AMOUNT,
        }
        response = self.client.post(
            reverse_lazy('expense:change', kwargs={'pk': self.expense.pk}),
            data,
        )
        self.assertIn(response.status_code, [302, constants.REDIRECTS])

    def test_expense_delete_view_unauthenticated(self):
        response = self.client.post(
            reverse_lazy('expense:delete', args=[self.expense.pk]),
        )
        self.assertIn(response.status_code, [302, constants.REDIRECTS])

    def test_expense_category_view_unauthenticated(self):
        response = self.client.get(reverse_lazy('expense:category_list'))
        self.assertIn(response.status_code, [302, constants.REDIRECTS])

    def test_expense_category_create_view_unauthenticated(self):
        data = {
            'name': 'Test',
            'parent_category': self.parent_category.pk,
        }
        response = self.client.post(
            reverse_lazy('expense:create_category'),
            data,
        )
        self.assertIn(response.status_code, [302, constants.REDIRECTS])

    def test_expense_category_delete_view_unauthenticated(self):
        response = self.client.post(
            reverse_lazy(
                'expense:delete_category_expense',
                args=[self.expense_type.pk],
            ),
        )
        self.assertIn(response.status_code, [302, constants.REDIRECTS])
