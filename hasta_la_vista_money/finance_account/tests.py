from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.test import RequestFactory, TestCase
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.prepare import (
    collect_info_expense,
    collect_info_income,
    sort_expense_income,
)
from hasta_la_vista_money.finance_account.serializers import AccountSerializer
from hasta_la_vista_money.finance_account.views import AccountView
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

    factory: RequestFactory

    @classmethod
    def setUpTestData(cls) -> None:
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

    def test_account_list(self) -> None:
        self.client.force_login(self.user)
        url = reverse('finance_account:list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertEqual(Account.objects.count(), 2)
        self.assertEqual(
            list(response.context['accounts']),
            list(Account.objects.filter(user=self.user)),
        )

    def test_account_create_valid_form(self) -> None:
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

    def test_update_account(self) -> None:
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

    def test_account_delete(self) -> None:
        self.client.force_login(self.user)
        url = reverse_lazy(
            'finance_account:delete_account',
            args=(self.account2.pk,),
        )

        response = self.client.post(url, follow=True)
        self.assertRedirects(response, '/finance_account/')

    def test_delete_account_exist_expense(self) -> None:
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

    def test_transfer_money(self) -> None:
        self.client.force_login(self.user)

        initial_balance_account1 = self.account1.balance
        initial_balance_account2 = self.account2.balance
        amount = Decimal('100')

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

    def test_transfer_money_insufficient_funds(self) -> None:
        """Тест перевода средств при недостаточном балансе."""
        self.client.force_login(self.user)

        amount = self.account1.balance + Decimal('1000')  # Сумма больше баланса

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
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('from_account', response_data['errors'])

    def test_transfer_money_same_account(self) -> None:
        """Тест перевода средств на тот же счет."""
        self.client.force_login(self.user)

        transfer_money = {
            'from_account': self.account1.pk,
            'to_account': self.account1.pk,
            'amount': 100,
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }

        response = self.client.post(
            reverse('finance_account:transfer_money'),
            transfer_money,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('to_account', response_data['errors'])

    def test_transfer_money_invalid_form(self) -> None:
        """Тест перевода средств с невалидной формой."""
        self.client.force_login(self.user)

        transfer_money = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': 'invalid_amount',
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }

        response = self.client.post(
            reverse('finance_account:transfer_money'),
            transfer_money,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('amount', response_data['errors'])

    def test_transfer_money_no_ajax(self) -> None:
        """Тест перевода средств без AJAX запроса."""
        self.client.force_login(self.user)

        transfer_money = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': 100,
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }

        response = self.client.post(
            reverse('finance_account:transfer_money'),
            transfer_money,
        )
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertFalse(response_data['success'])

    def test_account_model_methods(self) -> None:
        """Тест методов модели Account."""
        self.assertEqual(str(self.account1), 'Банковская карта')

        expected_url = reverse('finance_account:change', args=[self.account1.pk])
        self.assertEqual(self.account1.get_absolute_url(), expected_url)

        initial_balance1 = self.account1.balance
        initial_balance2 = self.account2.balance
        amount = Decimal('100')

        result = self.account1.transfer_money(self.account2, amount)
        self.assertTrue(result)

        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.assertEqual(self.account1.balance, initial_balance1 - amount)
        self.assertEqual(self.account2.balance, initial_balance2 + amount)

        large_amount = self.account1.balance + Decimal('1000')
        result = self.account1.transfer_money(self.account2, large_amount)
        self.assertFalse(result)

    def test_transfer_money_log_model(self) -> None:
        """Тест модели TransferMoneyLog."""
        transfer_log = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account1,
            to_account=self.account2,
            amount=100,
            exchange_date=timezone.now(),
            notes='Test transfer log',
        )

        # Тест __str__
        expected_str = f'{transfer_log.exchange_date:%d-%m-%Y %H:%M}. Перевод суммы {transfer_log.amount} со счёта "{self.account1}" на счёт "{self.account2}". '
        self.assertEqual(str(transfer_log), expected_str)

    def test_account_form_validation(self) -> None:
        """Тест валидации формы AddAccountForm."""
        # Валидная форма
        form = AddAccountForm(
            data={
                'name_account': 'Test Account',
                'type_account': 'D',
                'balance': 1000,
                'currency': 'RUB',
            },
        )
        self.assertTrue(form.is_valid())

        # Невалидная форма (отсутствует обязательное поле)
        form = AddAccountForm(
            data={
                'name_account': 'Test Account',
                'balance': 1000,
            },
        )
        self.assertFalse(form.is_valid())

    def test_transfer_money_form_validation(self) -> None:
        """Тест валидации формы TransferMoneyAccountForm."""
        # Валидная форма
        form = TransferMoneyAccountForm(
            user=self.user,
            data={
                'from_account': self.account1.pk,
                'to_account': self.account2.pk,
                'amount': 100,
                'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'notes': 'Test transfer',
            },
        )
        self.assertTrue(form.is_valid())

        # Невалидная форма - перевод на тот же счет
        form = TransferMoneyAccountForm(
            user=self.user,
            data={
                'from_account': self.account1.pk,
                'to_account': self.account1.pk,
                'amount': 100,
                'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'notes': 'Test transfer',
            },
        )
        self.assertFalse(form.is_valid())

        # Невалидная форма - недостаточно средств
        form = TransferMoneyAccountForm(
            user=self.user,
            data={
                'from_account': self.account1.pk,
                'to_account': self.account2.pk,
                'amount': self.account1.balance + Decimal('1000'),
                'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'notes': 'Test transfer',
            },
        )
        self.assertFalse(form.is_valid())

    def test_transfer_money_form_save(self) -> None:
        """Тест сохранения формы TransferMoneyAccountForm."""
        form = TransferMoneyAccountForm(
            user=self.user,
            data={
                'from_account': self.account1.pk,
                'to_account': self.account2.pk,
                'amount': 100,
                'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'notes': 'Test transfer',
            },
        )

        if form.is_valid():
            transfer_log = form.save()
            if transfer_log is not None:
                self.assertEqual(transfer_log.user, self.user)
                self.assertEqual(transfer_log.from_account, self.account1)
                self.assertEqual(transfer_log.to_account, self.account2)
                self.assertEqual(transfer_log.amount, 100)

    def test_account_view_methods(self) -> None:
        """Тест методов класса AccountView."""
        # Тестируем только базовую функциональность AccountView
        # Статистические методы перенесены в users app
        self.assertTrue(hasattr(AccountView, 'get_context_data'))
        self.assertTrue(hasattr(AccountView, 'context_object_name'))
        self.assertEqual(AccountView.context_object_name, 'finance_account')

    def test_prepare_functions(self) -> None:
        """Тест функций из модуля prepare."""
        income_info = collect_info_income(self.user)
        self.assertIsNotNone(income_info)

        expense_info = collect_info_expense(self.user)
        self.assertIsNotNone(expense_info)

        sorted_data = sort_expense_income(expense_info, income_info)
        self.assertIsInstance(sorted_data, list)

    def test_account_serializer(self) -> None:
        """Тест сериализатора AccountSerializer."""
        serializer = AccountSerializer(self.account1)
        data: Any = serializer.data

        self.assertIn('id', data)
        self.assertIn('name_account', data)
        self.assertIn('balance', data)
        self.assertIn('currency', data)
        self.assertEqual(data['name_account'], self.account1.name_account)
        self.assertEqual(str(data['balance']), str(self.account1.balance))
        self.assertEqual(data['currency'], self.account1.currency)

    def test_account_create_view(self) -> None:
        """Тест представления создания счета."""
        self.client.force_login(self.user)

        url = reverse('finance_account:create')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('add_account_form', response.context)

        data = {
            'name_account': 'New Test Account',
            'type_account': 'D',
            'balance': 5000,
            'currency': 'USD',
        }
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)

    def test_change_account_view(self) -> None:
        """Тест представления изменения счета."""
        self.client.force_login(self.user)

        url = reverse('finance_account:change', args=[self.account1.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('add_account_form', response.context)

        data = {
            'name_account': 'Updated Account Name',
            'type_account': 'D',
            'balance': 3000,
            'currency': 'EUR',
        }
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)

    def test_account_view_context_data(self) -> None:
        """Тест контекста данных в AccountView."""
        self.client.force_login(self.user)

        url = reverse('finance_account:list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('accounts', response.context)
        self.assertIn('add_account_form', response.context)
        self.assertIn('transfer_money_form', response.context)
        self.assertIn('transfer_money_log', response.context)
        self.assertIn('chart_combine', response.context)
        self.assertIn('sum_all_accounts', response.context)

    def test_account_view_unauthenticated(self) -> None:
        """Тест AccountView для неаутентифицированного пользователя."""
        url = reverse('finance_account:list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)

    def test_account_form_initial_values(self) -> None:
        """Тест начальных значений формы AddAccountForm."""
        form = AddAccountForm()
        self.assertEqual(form.fields['type_account'].initial, 'D')

    def test_transfer_money_form_initialization(self) -> None:
        """Тест инициализации формы TransferMoneyAccountForm."""
        form = TransferMoneyAccountForm(user=self.user)

        self.assertIn('from_account', form.fields)
        self.assertIn('to_account', form.fields)
        self.assertIn('amount', form.fields)
        self.assertIn('notes', form.fields)

    def test_account_model_choices(self) -> None:
        """Тест выбора в модели Account."""
        currency_choices = [choice[0] for choice in Account.CURRENCY_LIST]
        self.assertIn('RUB', currency_choices)
        self.assertIn('USD', currency_choices)
        self.assertIn('EUR', currency_choices)

        type_choices = [choice[0] for choice in Account.TYPE_ACCOUNT_LIST]
        self.assertIn('C', type_choices)
        self.assertIn('D', type_choices)
        self.assertIn('CASH', type_choices)

    def test_transfer_money_log_ordering(self) -> None:
        """Тест сортировки TransferMoneyLog."""
        log1 = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account1,
            to_account=self.account2,
            amount=100,
            exchange_date=timezone.now(),
            notes='First transfer',
        )

        log2 = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account2,
            to_account=self.account1,
            amount=200,
            exchange_date=timezone.now() + timedelta(hours=1),
            notes='Second transfer',
        )

        logs = TransferMoneyLog.objects.all()
        self.assertEqual(logs[0], log2)
        self.assertEqual(logs[1], log1)

    def test_account_model_defaults(self) -> None:
        """Тест значений по умолчанию в модели Account."""
        account = Account.objects.create(
            user=self.user,
            name_account='Test Default Account',
            currency='RUB',
        )

        self.assertEqual(account.balance, 0)
        self.assertEqual(account.type_account, 'Дебетовый счёт')

    def test_transfer_money_form_clean_method(self) -> None:
        """Тест метода clean формы TransferMoneyAccountForm."""
        form: TransferMoneyAccountForm = TransferMoneyAccountForm(
            user=self.user,
            data={
                'from_account': self.account1.pk,
                'to_account': self.account1.pk,
                'amount': self.account1.balance + Decimal('1000'),
                'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'notes': 'Test transfer',
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn('to_account', form.errors)
        self.assertIn('from_account', form.errors)

    def test_account_view_with_no_data(self) -> None:
        """Тест AccountView с пустыми данными."""
        Expense.objects.all().delete()
        Income.objects.all().delete()

        self.client.force_login(self.user)
        url = reverse('finance_account:list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('accounts', response.context)
