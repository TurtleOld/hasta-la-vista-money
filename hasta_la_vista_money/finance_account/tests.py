from decimal import Decimal

from django.test import TestCase
from django.urls import reverse_lazy
from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.users.models import User

BALANCE_TEST = 250000
NEW_BALANCE_TEST = 450000


class TestAccount(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'expense.yaml',
        'expense_cat.yaml',
        'income.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account1 = Account.objects.get(pk=1)
        self.account2 = Account.objects.get(pk=2)
        self.expense = Expense.objects.get(pk=1)
        self.income = Income.objects.get(pk=1)

    def test_account_list(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('applications:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        account_list = list(response.context['accounts'])
        self.assertQuerySetEqual(account_list, [self.account1, self.account2])

    def test_account_create(self):
        self.client.force_login(self.user)
        url = reverse_lazy('finance_account:create')

        new_account = {
            'user': self.user,
            'name_account': 'Банковская карта *8090',
            'balance': BALANCE_TEST,
            'currency': 'RUB',
        }

        response = self.client.post(url, data=new_account, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

        created_account = Account.objects.get(
            name_account='Банковская карта *8090',
        )
        self.assertEqual(created_account.balance, BALANCE_TEST)
        self.assertEqual(created_account.currency, 'RUB')

    def test_update_account(self):
        self.client.force_login(self.user)
        url = reverse_lazy('finance_account:change', args=(self.account1.pk,))
        update_account = {
            'user': self.user,
            'name_account': 'Основной счёт',
            'balance': NEW_BALANCE_TEST,
            'currency': 'RUB',
        }
        response = self.client.post(url, update_account, follow=True)
        self.assertEqual(
            Account.objects.get(pk=self.account1.pk),
            self.account1,
        )
        self.assertRedirects(
            response,
            '/finance_account/',
            status_code=constants.REDIRECTS,
        )

    def test_account_delete(self):
        self.client.force_login(self.user)
        url = reverse_lazy(
            'finance_account:delete_account',
            args=(self.account2.pk,),
        )

        response = self.client.post(url, follow=True)
        self.assertRedirects(response, '/finance_account/')

    def test_delete_account_exist_expense(self):
        self.client.force_login(self.user)

        url2 = reverse_lazy(
            'finance_account:delete_account',
            args=(self.account1.pk,),
        )

        expense_exists = Expense.objects.filter(
            account__name_account=self.account1.name_account,
        ).exists()
        self.assertTrue(expense_exists)

        response = self.client.post(url2, follow=True)
        self.assertContains(
            response,
            'Счёт не может быть удалён!',
        )
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertTrue(Account.objects.filter(pk=self.account1.pk).exists())

    def test_transfer_money(self):
        self.client.force_login(self.user)
        url = reverse_lazy('finance_account:transfer_money')

        transfer_money = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': constants.ONE_HUNDRED,
            'exchange_date': '2024-01-24',
            'notes': 'Test transfer',
        }
        initial_balance_account1 = self.account1.balance
        initial_balance_account2 = self.account2.balance

        response = self.client.post(
            url,
            data=transfer_money,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

        account1 = Account.objects.get(pk=self.account1.pk)
        account2 = Account.objects.get(pk=self.account2.pk)

        transfer_money_amount = Decimal(transfer_money['amount'])  # type: ignore[arg-type]

        self.assertEqual(
            account1.balance,
            initial_balance_account1 - transfer_money_amount,
        )
        self.assertEqual(
            account2.balance,
            initial_balance_account2 + transfer_money_amount,
        )
