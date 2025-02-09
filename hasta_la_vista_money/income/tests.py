from django.test import TestCase
from django.urls import reverse_lazy
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.forms import AddCategoryIncomeForm, IncomeForm
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User

TEST_AMOUNT = 15000
NEW_TEST_AMOUNT = 25000


class TestIncome(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'income.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.income = Income.objects.get(pk=1)
        self.income_type = IncomeCategory.objects.get(pk=1)
        self.parent_category = IncomeCategory.objects.get(name='Зарплата')

    def test_list_income(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('income:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_create(self):
        self.client.force_login(self.user)

        url = reverse_lazy('income:create')

        new_income = {
            'user': self.user,
            'account': self.account,
            'category': self.income_type,
            'date': '2023-12-20 15:30',
            'amount': TEST_AMOUNT,
        }

        form = IncomeForm(data=new_income, user=self.user, depth=3)
        self.assertTrue(form.is_valid())

        response = self.client.post(url, data=form.data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_update(self):
        self.client.force_login(self.user)
        url = reverse_lazy('income:change', args=(self.income.pk,))
        update_income = {
            'user': self.user,
            'category': self.income_type.id,
            'account': self.account.id,
            'date': '2023-06-30 22:31:54',
            'amount': NEW_TEST_AMOUNT,
        }

        form = IncomeForm(data=update_income, user=self.user, depth=3)
        self.assertTrue(form.is_valid())

        response = self.client.post(url, form.data)
        self.assertEqual(response.status_code, constants.REDIRECTS)

        updated_expense = Income.objects.get(pk=self.income.id)
        self.assertEqual(updated_expense.amount, NEW_TEST_AMOUNT)

    def test_income_delete(self):
        self.client.force_login(self.user)

        url = reverse_lazy('income:delete_income', args=(self.income.pk,))

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_category_income_create(self):
        self.client.force_login(self.user)

        new_category = {
            'name': 'Вторая часть',
            'parent_category': self.parent_category.id,
        }

        form = AddCategoryIncomeForm(data=new_category, user=self.user, depth=3)
        self.assertTrue(form.is_valid())

    def test_category_income_delete(self):
        self.client.force_login(self.user)

        url = reverse_lazy(
            'income:delete_category_income',
            args=(self.income.pk,),
        )

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
