"""Tests for finance account forms."""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.constants import ACCOUNT_TYPE_CREDIT
from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.users.models import User


class TestAddAccountForm(TestCase):
    """Test cases for AddAccountForm."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_form_initialization(self) -> None:
        """Test form initialization with default values."""
        form = AddAccountForm()

        self.assertEqual(
            form.fields['type_account'].initial,
            Account.TYPE_ACCOUNT_LIST[1][0],
        )

        for field in form.fields.values():
            if hasattr(field.widget, 'attrs'):
                self.assertIn(
                    'form-control',
                    field.widget.attrs.get('class', ''),
                )

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
            'type_account': ACCOUNT_TYPE_CREDIT,
            'bank': 'SBERBANK',
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
            'type_account': ACCOUNT_TYPE_CREDIT,
            'balance': Decimal('0.00'),
            'currency': 'RUB',
        }
        form = AddAccountForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_form_validation_missing_required_fields(self) -> None:
        """Test form validation with missing required fields."""
        form_data = {
            'name_account': 'Test Account',
            'balance': Decimal('1000.00'),
        }
        form = AddAccountForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_form_validation_invalid_currency(self) -> None:
        """Test form validation with invalid currency."""
        form_data = {
            'name_account': 'Test Account',
            'type_account': 'Debit',
            'balance': Decimal('1000.00'),
            'currency': 'INVALID',
        }
        form = AddAccountForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_form_validation_negative_balance(self) -> None:
        """Test form validation with negative balance."""
        form_data = {
            'name_account': 'Test Account',
            'type_account': 'Debit',
            'balance': Decimal('-1000.00'),
            'currency': 'RUB',
        }
        form = AddAccountForm(data=form_data)
        self.assertFalse(form.is_valid())

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

    def test_form_save_with_commit(self) -> None:
        """Test form save with commit=True."""
        form_data = {
            'name_account': 'Test Account',
            'type_account': 'Debit',
            'balance': Decimal('1000.00'),
            'currency': 'RUB',
        }
        form = AddAccountForm(data=form_data)
        self.assertTrue(form.is_valid())

        account = form.save(commit=True)
        self.assertIsInstance(account, Account)
        self.assertEqual(account.name_account, 'Test Account')


class TestTransferMoneyAccountForm(TestCase):
    """Test cases for TransferMoneyAccountForm."""

    def setUp(self) -> None:
        """Set up test data."""
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

    def test_form_initialization_with_initial_data(self) -> None:
        """Test form initialization with initial data."""
        initial_data = {
            'from_account': self.account1,
            'to_account': self.account2,
        }
        form = TransferMoneyAccountForm(user=self.user, initial=initial_data)

        self.assertEqual(form.initial['from_account'], self.account1)
        self.assertEqual(form.initial['to_account'], self.account2)

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

    def test_form_validation_zero_amount(self) -> None:
        """Test form validation with zero amount."""
        form_data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': Decimal('0.00'),
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('amount', form.errors)

    def test_form_validation_missing_required_fields(self) -> None:
        """Test form validation with missing required fields."""
        form_data = {
            'from_account': self.account1.pk,
            'amount': Decimal('100.00'),
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)
        self.assertFalse(form.is_valid())

    def test_form_validation_invalid_account(self) -> None:
        """Test form validation with invalid account."""
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123',
        )
        other_account = Account.objects.create(
            user=other_user,
            name_account='Other Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

        form_data = {
            'from_account': other_account.pk,
            'to_account': self.account2.pk,
            'amount': Decimal('100.00'),
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)
        self.assertFalse(form.is_valid())

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

    def test_form_clean_method(self) -> None:
        """Test form clean method validation."""
        form_data = {
            'from_account': self.account1.pk,
            'to_account': self.account1.pk,
            'amount': self.account1.balance + Decimal('1000.00'),
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }
        form = TransferMoneyAccountForm(user=self.user, data=form_data)

        self.assertFalse(form.is_valid())
        self.assertIn('to_account', form.errors)
        self.assertIn('from_account', form.errors)
