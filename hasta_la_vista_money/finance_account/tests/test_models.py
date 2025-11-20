"""Tests for finance account models."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT,
    ACCOUNT_TYPE_CREDIT_CARD,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.services import AccountService
from hasta_la_vista_money.users.models import User


class TestAccountModel(TestCase):
    """Test cases for Account model."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_account_creation(self) -> None:
        """Test account creation with default values."""
        account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            currency='RUB',
        )

        self.assertEqual(account.balance, Decimal('0.00'))
        self.assertEqual(account.type_account, 'Debit')
        self.assertEqual(account.name_account, 'Test Account')
        self.assertEqual(account.currency, 'RUB')
        self.assertEqual(account.user, self.user)

    def test_account_str_representation(self) -> None:
        """Test string representation of Account."""
        account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            currency='RUB',
        )

        self.assertEqual(str(account), 'Test Account')

    def test_account_get_absolute_url(self) -> None:
        """Test get_absolute_url method."""
        account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            currency='RUB',
        )

        expected_url = f'/finance_account/change/{account.pk}/'
        self.assertEqual(account.get_absolute_url(), expected_url)

    def test_account_transfer_money_success(self) -> None:
        """Test successful money transfer between accounts."""
        account1 = Account.objects.create(
            user=self.user,
            name_account='Account 1',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        account2 = Account.objects.create(
            user=self.user,
            name_account='Account 2',
            balance=Decimal('500.00'),
            currency='RUB',
        )

        amount = Decimal('200.00')
        result = account1.transfer_money(account2, amount)

        self.assertTrue(result)
        account1.refresh_from_db()
        account2.refresh_from_db()

        self.assertEqual(account1.balance, Decimal('800.00'))
        self.assertEqual(account2.balance, Decimal('700.00'))

    def test_account_transfer_money_insufficient_funds(self) -> None:
        """Test money transfer with insufficient funds."""
        account1 = Account.objects.create(
            user=self.user,
            name_account='Account 1',
            balance=Decimal('100.00'),
            currency='RUB',
        )
        account2 = Account.objects.create(
            user=self.user,
            name_account='Account 2',
            balance=Decimal('500.00'),
            currency='RUB',
        )

        amount = Decimal('200.00')
        result = account1.transfer_money(account2, amount)

        self.assertFalse(result)
        account1.refresh_from_db()
        account2.refresh_from_db()

        self.assertEqual(account1.balance, Decimal('100.00'))
        self.assertEqual(account2.balance, Decimal('500.00'))

    def test_account_transfer_money_zero_amount(self) -> None:
        """Test money transfer with zero amount."""
        account1 = Account.objects.create(
            user=self.user,
            name_account='Account 1',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        account2 = Account.objects.create(
            user=self.user,
            name_account='Account 2',
            balance=Decimal('500.00'),
            currency='RUB',
        )

        amount = Decimal('0.00')
        result = account1.transfer_money(account2, amount)

        self.assertFalse(result)

    def test_account_transfer_money_negative_amount(self) -> None:
        """Test money transfer with negative amount."""
        account1 = Account.objects.create(
            user=self.user,
            name_account='Account 1',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        account2 = Account.objects.create(
            user=self.user,
            name_account='Account 2',
            balance=Decimal('500.00'),
            currency='RUB',
        )

        amount = Decimal('-100.00')
        result = account1.transfer_money(account2, amount)

        self.assertFalse(result)

    def test_account_get_credit_card_debt(self) -> None:
        """Test get_credit_card_debt method."""
        account = Account.objects.create(
            user=self.user,
            name_account='Credit Card',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('-1000.00'),
            currency='RUB',
        )

        account_service = AccountService()
        debt = account_service.get_credit_card_debt(account)
        # Since there are no expenses/income records, debt should be 0
        self.assertEqual(debt, Decimal('0.00'))

    def test_account_get_credit_card_debt_positive_balance(self) -> None:
        """Test get_credit_card_debt with positive balance."""
        account = Account.objects.create(
            user=self.user,
            name_account='Credit Card',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('1000.00'),
            currency='RUB',
        )

        account_service = AccountService()
        debt = account_service.get_credit_card_debt(account)
        self.assertEqual(debt, Decimal('0.00'))

    def test_account_calculate_grace_period_info(self) -> None:
        """Test calculate_grace_period_info method."""
        account = Account.objects.create(
            user=self.user,
            name_account='Credit Card',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('-1000.00'),
            limit_credit=Decimal('5000.00'),
            payment_due_date=timezone.now().date() + timedelta(days=10),
            grace_period_days=30,
            currency='RUB',
        )

        account_service = AccountService()
        info = account_service.calculate_grace_period_info(
            account,
            timezone.now().date(),
        )

        self.assertIn('final_debt', info)
        self.assertIn('days_until_due', info)
        self.assertIn('purchase_month', info)
        self.assertIn('purchase_start', info)
        self.assertIn('purchase_end', info)
        self.assertIn('grace_end', info)

    def test_account_model_choices(self) -> None:
        """Test model choices."""
        currency_choices = [choice[0] for choice in Account.CURRENCY_LIST]
        self.assertIn('RUB', currency_choices)
        self.assertIn('USD', currency_choices)
        self.assertIn('EUR', currency_choices)

        type_choices = [choice[0] for choice in Account.TYPE_ACCOUNT_LIST]
        self.assertIn('Debit', type_choices)
        self.assertIn(ACCOUNT_TYPE_CREDIT, type_choices)
        self.assertIn(ACCOUNT_TYPE_CREDIT_CARD, type_choices)

    def test_account_model_meta(self) -> None:
        """Test model meta options."""
        self.assertEqual(Account._meta.verbose_name, 'Счёт')
        self.assertEqual(Account._meta.verbose_name_plural, 'Счета')
        self.assertEqual(Account._meta.ordering, ['name_account'])


class TestTransferMoneyLogModel(TestCase):
    """Test cases for TransferMoneyLog model."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )
        self.account1 = Account.objects.create(
            user=self.user,
            name_account='Account 1',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.account2 = Account.objects.create(
            user=self.user,
            name_account='Account 2',
            balance=Decimal('500.00'),
            currency='RUB',
        )

    def test_transfer_money_log_creation(self) -> None:
        """Test TransferMoneyLog creation."""
        transfer_log = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account1,
            to_account=self.account2,
            amount=Decimal('200.00'),
            exchange_date=timezone.now(),
            notes='Test transfer',
        )

        self.assertEqual(transfer_log.user, self.user)
        self.assertEqual(transfer_log.from_account, self.account1)
        self.assertEqual(transfer_log.to_account, self.account2)
        self.assertEqual(transfer_log.amount, Decimal('200.00'))
        self.assertEqual(transfer_log.notes, 'Test transfer')

    def test_transfer_money_log_str_representation(self) -> None:
        """Test string representation of TransferMoneyLog."""
        exchange_date = timezone.now()
        transfer_log = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account1,
            to_account=self.account2,
            amount=Decimal('200.00'),
            exchange_date=exchange_date,
            notes='Test transfer',
        )

        expected_str = (
            f'{exchange_date:%d-%m-%Y %H:%M}. '
            f'Перевод суммы {transfer_log.amount} со счёта '
            f'"{self.account1}" на счёт "{self.account2}". '
        )
        self.assertEqual(str(transfer_log), expected_str)

    def test_transfer_money_log_ordering(self) -> None:
        """Test TransferMoneyLog ordering."""
        log1 = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account1,
            to_account=self.account2,
            amount=Decimal('100.00'),
            exchange_date=timezone.now(),
            notes='First transfer',
        )

        log2 = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account2,
            to_account=self.account1,
            amount=Decimal('200.00'),
            exchange_date=timezone.now() + timedelta(hours=1),
            notes='Second transfer',
        )

        logs = TransferMoneyLog.objects.all()
        self.assertEqual(logs[0], log2)
        self.assertEqual(logs[1], log1)

    def test_transfer_money_log_model_meta(self) -> None:
        """Test TransferMoneyLog model meta options."""
        self.assertEqual(
            TransferMoneyLog._meta.verbose_name, 'Лог перевода денег'
        )
        self.assertEqual(
            TransferMoneyLog._meta.verbose_name_plural, 'Логи переводов денег'
        )
        self.assertEqual(TransferMoneyLog._meta.ordering, ['-exchange_date'])


class TestAccountManagers(TestCase):
    """Test cases for Account model managers."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user1 = User.objects.create_user(
            username='user1',
            password='testpass123',
        )
        self.user2 = User.objects.create_user(
            username='user2',
            password='testpass123',
        )

        self.account1 = Account.objects.create(
            user=self.user1,
            name_account='User1 Account',
            currency='RUB',
        )
        self.account2 = Account.objects.create(
            user=self.user2,
            name_account='User2 Account',
            currency='RUB',
        )

    def test_by_user_manager(self) -> None:
        """Test by_user manager method."""
        user1_accounts = Account.objects.by_user(self.user1)
        user2_accounts = Account.objects.by_user(self.user2)

        self.assertIn(self.account1, user1_accounts)
        self.assertNotIn(self.account2, user1_accounts)
        self.assertIn(self.account2, user2_accounts)
        self.assertNotIn(self.account1, user2_accounts)

    def test_by_user_manager_empty_result(self) -> None:
        """Test by_user manager with user having no accounts."""
        user3 = User.objects.create_user(
            username='user3',
            password='testpass123',
        )

        user3_accounts = Account.objects.by_user(user3)
        self.assertEqual(user3_accounts.count(), 0)
