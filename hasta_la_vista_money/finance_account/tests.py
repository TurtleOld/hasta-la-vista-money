from django.utils import timezone

from django.contrib import messages
from django.test import RequestFactory, TestCase
from django.urls import reverse_lazy, reverse
from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.forms import AddAccountForm
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

    @classmethod
    def setUpTestData(cls):
        cls.factory = RequestFactory()

    def setUp(self) -> None:
        # Получаем пользователя из фикстуры
        self.user = User.objects.get(id=1)

        # Привязываем аккаунты к пользователю
        self.account1 = Account.objects.get(name_account='Банковская карта')
        self.account1.user = self.user
        self.account1.save()

        self.account2 = Account.objects.get(name_account='Основной счёт')
        self.account2.user = self.user
        self.account2.save()

        self.expense1 = Expense.objects.get(pk=1)
        self.expense1.account = self.account1
        self.expense1.user = self.user
        self.expense1.save()

        self.income1 = Income.objects.get(pk=1)
        self.income1.account = self.account1
        self.income1.user = self.user
        self.income1.save()

    def test_account_list(self):
        self.client.force_login(self.user)
        url = reverse('finance_account:list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertEqual(Account.objects.count(), 2)
        self.assertQuerySetEqual(
            response.context['accounts'],
            Account.objects.filter(user=self.user),
            transform=lambda x: x,
        )

    def test_account_create_valid_form(self):
        account_form = AddAccountForm(
            data={
                'name': 'Test Account',
                'balance': 1000,
                'currency': 'USD',
            },
        )
        request = self.factory.post('/')
        request.user = self.user

        if account_form.is_valid():
            add_account = account_form.save(commit=False)
            add_account.user = self.user
            add_account.save()
            messages.success(
                request,
                'Счет успешно создан',
            )
            response_data = {'success': True}
            self.assertEqual(response_data, {'success': True})
            self.assertEqual(Account.objects.count(), 1)
            account = Account.objects.get()
            self.assertEqual(account.name_account, 'Test Account')
            self.assertEqual(account.balance, 1000)
            self.assertEqual(account.currency, 'USD')
            self.assertIn(
                'Счет успешно создан',
                [m.message for m in messages.get_messages(request)],
            )

    def test_update_account(self):
        self.client.force_login(self.user)
        url = reverse_lazy('finance_account:change', args=(self.account1.pk,))
        update_account = {
            'user': self.user,
            'type_account': 'D',
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

        expense_exists = Expense.objects.filter(account=self.account1).exists()
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

        initial_balance_account1 = self.account1.balance
        initial_balance_account2 = self.account2.balance
        amount = constants.ONE_HUNDRED

        transfer_money = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': amount,
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }

        response = self.client.post(
            reverse('finance_account:transfer_money'),
            transfer_money,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})

        self.account1.refresh_from_db()
        self.account2.refresh_from_db()

        self.assertEqual(self.account1.balance, initial_balance_account1 - amount)
        self.assertEqual(self.account2.balance, initial_balance_account2 + amount)
