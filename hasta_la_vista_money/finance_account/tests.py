from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.forms import ValidationError
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
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_credit_fields_required,
    validate_different_accounts,
    validate_positive_amount,
)
from hasta_la_vista_money.finance_account.views import AccountView
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.finance_account import services as account_services

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
            list(response.context['finance_account']),
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
            'type_account': 'Debit',
            'limit_credit': 1000,
            'payment_due_date': '2022-01-01',
            'grace_period_days': 120,
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
                'type_account': 'Debit',
                'limit_credit': 1000,
                'payment_due_date': '2022-01-01',
                'grace_period_days': 120,
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
            'type_account': 'Credit',
            'limit_credit': 1000,
            'payment_due_date': '2022-01-01',
            'grace_period_days': 120,
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
            'type_account': 'Credit',
            'limit_credit': 1000,
            'payment_due_date': '2022-01-01',
            'grace_period_days': 120,
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
        self.assertIn('finance_account', response.context)
        self.assertIn('add_account_form', response.context)
        self.assertIn('transfer_money_form', response.context)
        self.assertIn('transfer_money_log', response.context)
        self.assertIn('sum_all_accounts', response.context)

    def test_account_view_unauthenticated(self) -> None:
        """Тест AccountView для неаутентифицированного пользователя."""
        url = reverse('finance_account:list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)

    def test_account_form_initial_values(self) -> None:
        """Тест начальных значений формы AddAccountForm."""
        form = AddAccountForm()
        self.assertEqual(form.fields['type_account'].initial, 'Debit')

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
        self.assertIn('Credit', type_choices)
        self.assertIn('Debit', type_choices)
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
        self.assertEqual(account.type_account, 'Debit')

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
        self.assertIn('finance_account', response.context)


class TestAccountServices(TestCase):
    """
    Unit tests for account service functions (get_accounts_for_user_or_group, get_sum_all_accounts, get_transfer_money_log).
    """

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'expense.yaml',
        'expense_cat.yaml',
        'income.yaml',
        'income_cat.yaml',
        'loan.yaml',
        'receipt_receipt.yaml',
        'receipt_product.yaml',
        'receipt_seller.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(id=1)
        self.account1 = Account.objects.filter(user=self.user).first()
        self.group = self.user.groups.first()
        if self.group:
            self.group_id = str(self.group.id)
        else:
            self.group_id = None

    def test_get_accounts_for_user(self):
        """Test that get_accounts_for_user_or_group returns only user's accounts when group_id is None or 'my'."""
        accounts = account_services.get_accounts_for_user_or_group(self.user, None)
        self.assertTrue(all(acc.user == self.user for acc in accounts))
        accounts_my = account_services.get_accounts_for_user_or_group(self.user, 'my')
        self.assertTrue(all(acc.user == self.user for acc in accounts_my))

    def test_get_accounts_for_group(self):
        """Test that get_accounts_for_user_or_group returns all accounts for users in the group."""
        if not self.group_id:
            self.skipTest('User has no group for group test')
        accounts = account_services.get_accounts_for_user_or_group(
            self.user, self.group_id
        )
        group_users = list(self.group.user_set.all())
        self.assertTrue(all(acc.user in group_users for acc in accounts))

    def test_get_sum_all_accounts(self):
        """Test that get_sum_all_accounts returns correct sum for queryset."""
        accounts = Account.objects.filter(user=self.user)
        expected_sum = sum(acc.balance for acc in accounts)
        result = account_services.get_sum_all_accounts(accounts)
        self.assertEqual(result, expected_sum)

    def test_get_transfer_money_log(self):
        """Test that get_transfer_money_log returns recent logs for user."""
        logs = account_services.get_transfer_money_log(self.user)
        self.assertTrue(all(log.user == self.user for log in logs))
        self.assertLessEqual(len(logs), 10)


class TestAccountBusinessLogic(TestCase):
    """
    Unit tests for Account model business logic methods: transfer_money, get_credit_card_debt, calculate_grace_period_info.
    """

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'expense.yaml',
        'expense_cat.yaml',
        'income.yaml',
        'income_cat.yaml',
    ]

    def setUp(self):
        self.user = User.objects.get(id=1)
        self.account1 = Account.objects.get(name_account='Банковская карта')
        self.account2 = Account.objects.get(name_account='Основной счёт')
        self.account1.user = self.user
        self.account2.user = self.user
        self.account1.save()
        self.account2.save()

    def test_transfer_money_success(self):
        amount = Decimal('100')
        initial_balance_1 = self.account1.balance
        initial_balance_2 = self.account2.balance
        result = self.account1.transfer_money(self.account2, amount)
        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(self.account1.balance, initial_balance_1 - amount)
        self.assertEqual(self.account2.balance, initial_balance_2 + amount)

    def test_transfer_money_insufficient(self):
        amount = self.account1.balance + Decimal('1')
        result = self.account1.transfer_money(self.account2, amount)
        self.assertFalse(result)

    def test_get_credit_card_debt(self):
        self.account1.type_account = 'CreditCard'
        self.account1.save()
        debt = self.account1.get_credit_card_debt()
        self.assertIsInstance(debt, Decimal)

    def test_calculate_grace_period_info(self):
        self.account1.type_account = 'CreditCard'
        self.account1.save()
        from datetime import date

        info = self.account1.calculate_grace_period_info(date.today())
        self.assertIn('final_debt', info)


class TestValidatorsRefactored(TestCase):
    """Test custom validators for finance account forms."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )
        self.account1 = Account.objects.create(
            user=self.user,
            name_account='Test Account 1',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.account2 = Account.objects.create(
            user=self.user,
            name_account='Test Account 2',
            balance=Decimal('500.00'),
            currency='RUB',
        )

    def test_validate_positive_amount_valid(self) -> None:
        """Test positive amount validation with valid amount."""
        amount = Decimal('100.00')
        validate_positive_amount(amount)

    def test_validate_positive_amount_invalid(self) -> None:
        """Test positive amount validation with invalid amount."""
        amount = Decimal('0.00')
        with self.assertRaises(ValidationError):
            validate_positive_amount(amount)

    def test_validate_account_balance_sufficient(self) -> None:
        """Test account balance validation with sufficient funds."""
        amount = Decimal('500.00')
        validate_account_balance(self.account1, amount)

    def test_validate_account_balance_insufficient(self) -> None:
        """Test account balance validation with insufficient funds."""
        amount = Decimal('1500.00')
        with self.assertRaises(ValidationError):
            validate_account_balance(self.account1, amount)

    def test_validate_different_accounts_valid(self) -> None:
        """Test different accounts validation with different accounts."""
        validate_different_accounts(self.account1, self.account2)

    def test_validate_different_accounts_invalid(self) -> None:
        """Test different accounts validation with same account."""
        with self.assertRaises(ValidationError):
            validate_different_accounts(self.account1, self.account1)

    def test_validate_credit_fields_required_credit_account(self) -> None:
        """Test credit fields validation for credit account."""
        validate_credit_fields_required(
            type_account='Credit',
            limit_credit=Decimal('10000.00'),
            payment_due_date=timezone.now().date(),
            grace_period_days=30,
        )

    def test_validate_credit_fields_required_missing_fields(self) -> None:
        """Test credit fields validation with missing fields."""
        with self.assertRaises(ValidationError):
            validate_credit_fields_required(
                type_account='Credit',
                limit_credit=None,
                payment_due_date=None,
                grace_period_days=None,
            )

    def test_validate_credit_fields_required_debit_account(self) -> None:
        """Test credit fields validation for debit account (should pass)."""
        validate_credit_fields_required(
            type_account='Debit',
            limit_credit=None,
            payment_due_date=None,
            grace_period_days=None,
        )


class TestAddAccountFormRefactored(TestCase):
    """Test refactored AddAccountForm."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_form_initialization(self) -> None:
        """Test form initialization with default values."""
        form = AddAccountForm()

        self.assertEqual(
            form.fields['type_account'].initial, Account.TYPE_ACCOUNT_LIST[1][0]
        )

        for field_name, field in form.fields.items():
            if hasattr(field.widget, 'attrs'):
                self.assertIn('form-control', field.widget.attrs.get('class', ''))

    def test_form_validation_valid_data(self) -> None:
        """Test form validation with valid data."""
        form_data = {
            'name_account': 'Test Account',
            'type_account': 'Debit',
            'balance': Decimal('1000.00'),
            'currency': 'RUB',
        }
        form = AddAccountForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_form_validation_credit_account_valid(self) -> None:
        """Test form validation for credit account with all required fields."""
        form_data = {
            'name_account': 'Credit Card',
            'type_account': 'Credit',
            'limit_credit': Decimal('10000.00'),
            'payment_due_date': timezone.now().date(),
            'grace_period_days': 30,
            'balance': Decimal('0.00'),
            'currency': 'RUB',
        }
        form = AddAccountForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_form_validation_credit_account_missing_fields(self) -> None:
        """Test form validation for credit account with missing fields."""
        form_data = {
            'name_account': 'Credit Card',
            'type_account': 'Credit',
            'balance': Decimal('0.00'),
            'currency': 'RUB',
        }
        form = AddAccountForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_form_save(self) -> None:
        """Test form save functionality."""
        form_data = {
            'name_account': 'Test Account',
            'type_account': 'Debit',
            'balance': Decimal('1000.00'),
            'currency': 'RUB',
        }
        form = AddAccountForm(data=form_data)
        self.assertTrue(form.is_valid())

        account = form.save(commit=False)
        account.user = self.user
        account.save()

        self.assertEqual(account.name_account, 'Test Account')
        self.assertEqual(account.balance, Decimal('1000.00'))
        self.assertEqual(account.currency, 'RUB')


class TestTransferMoneyAccountFormRefactored(TestCase):
    """Test refactored TransferMoneyAccountForm."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )
        self.account1 = Account.objects.create(
            user=self.user,
            name_account='Test Account 1',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.account2 = Account.objects.create(
            user=self.user,
            name_account='Test Account 2',
            balance=Decimal('500.00'),
            currency='RUB',
        )

    def test_form_initialization(self) -> None:
        """Test form initialization with user accounts."""
        form = TransferMoneyAccountForm(user=self.user)

        self.assertEqual(form.fields['from_account'].queryset.count(), 2)

        self.assertIn('amount', form.fields)
        self.assertIn('notes', form.fields)

        for field_name, field in form.fields.items():
            if hasattr(field.widget, 'attrs'):
                widget_class = field.widget.attrs.get('class', '')
                self.assertIn(
                    'form-control',
                    widget_class,
                    f'Field {field_name} missing form-control class',
                )

    def test_form_validation_valid_data(self) -> None:
        """Test form validation with valid data."""
        form_data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': Decimal('100.00'),
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)
        self.assertTrue(form.is_valid())

    def test_form_validation_same_accounts(self) -> None:
        """Test form validation with same source and destination accounts."""
        form_data = {
            'from_account': self.account1.pk,
            'to_account': self.account1.pk,
            'amount': Decimal('100.00'),
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('to_account', form.errors)

    def test_form_validation_insufficient_funds(self) -> None:
        """Test form validation with insufficient funds."""
        form_data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': Decimal('1500.00'),
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('from_account', form.errors)

    def test_form_validation_negative_amount(self) -> None:
        """Test form validation with negative amount."""
        form_data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': Decimal('-100.00'),
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('amount', form.errors)

    def test_form_save(self) -> None:
        """Test form save functionality using TransferService."""
        form_data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': Decimal('100.00'),
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)
        self.assertTrue(form.is_valid())

        transfer_log = form.save()

        self.assertIsInstance(transfer_log, TransferMoneyLog)
        self.assertEqual(transfer_log.from_account, self.account1)
        self.assertEqual(transfer_log.to_account, self.account2)
        self.assertEqual(transfer_log.amount, Decimal('100.00'))
        self.assertEqual(transfer_log.user, self.user)

        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.assertEqual(self.account1.balance, Decimal('900.00'))
        self.assertEqual(self.account2.balance, Decimal('600.00'))

    def test_form_save_without_commit(self) -> None:
        """Test form save without commit raises error."""
        form_data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': Decimal('100.00'),
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)
        self.assertTrue(form.is_valid())

        with self.assertRaises(ValueError):
            form.save(commit=False)
