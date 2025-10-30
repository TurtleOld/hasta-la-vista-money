"""Tests for finance account validators."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.constants import ACCOUNT_TYPE_CREDIT
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_credit_fields_required,
    validate_different_accounts,
    validate_positive_amount,
)
from hasta_la_vista_money.users.models import User


class TestValidatePositiveAmount(TestCase):
    """Test cases for validate_positive_amount validator."""

    def test_validate_positive_amount_valid(self) -> None:
        """Test positive amount validation with valid amount."""
        amount = Decimal('100.00')
        validate_positive_amount(amount)

    def test_validate_positive_amount_zero(self) -> None:
        """Test positive amount validation with zero amount."""
        amount = Decimal('0.00')
        with self.assertRaises(ValidationError) as context:
            validate_positive_amount(amount)

        self.assertIn('Сумма должна быть больше нуля', str(context.exception))

    def test_validate_positive_amount_negative(self) -> None:
        """Test positive amount validation with negative amount."""
        amount = Decimal('-100.00')
        with self.assertRaises(ValidationError) as context:
            validate_positive_amount(amount)

        self.assertIn('Сумма должна быть больше нуля', str(context.exception))

    def test_validate_positive_amount_very_small(self) -> None:
        """Test positive amount validation with very small amount."""
        amount = Decimal('0.01')
        validate_positive_amount(amount)

    def test_validate_positive_amount_large(self) -> None:
        """Test positive amount validation with large amount."""
        amount = Decimal('999999.99')
        validate_positive_amount(amount)

    def test_validate_positive_amount_parametrized(self) -> None:
        """Параметризация: некорректные и граничные значения
        разных типов на входе positive_amount.
        """
        invalid_cases = [
            0,
            -1,
            -0.01,
            Decimal('0.00'),
            Decimal('-999.00'),
            None,
            '0',
            '-5',
            '',
            object(),
        ]
        for value in invalid_cases:
            with (
                self.subTest(value=value),
                self.assertRaises(
                    (ValidationError, TypeError, InvalidOperation)
                ),
            ):
                validate_positive_amount(value)
        valid_cases = [
            1,
            0.5,
            Decimal('0.01'),
            '10.25',
        ]
        for value in valid_cases:
            with self.subTest(value=value):
                validate_positive_amount(Decimal(value))


class TestValidateAccountBalance(TestCase):
    """Test cases for validate_account_balance validator."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def test_validate_account_balance_sufficient(self) -> None:
        """Test account balance validation with sufficient funds."""
        amount = Decimal('500.00')
        validate_account_balance(self.account, amount)

    def test_validate_account_balance_exact(self) -> None:
        """Test account balance validation with exact balance."""
        amount = Decimal('1000.00')
        validate_account_balance(self.account, amount)

    def test_validate_account_balance_insufficient(self) -> None:
        """Test account balance validation with insufficient funds."""
        amount = Decimal('1500.00')
        with self.assertRaises(ValidationError) as context:
            validate_account_balance(self.account, amount)

        self.assertIn('Недостаточно средств на счете', str(context.exception))

    def test_validate_account_balance_zero_account(self) -> None:
        """Test account balance validation with zero balance account."""
        zero_account = Account.objects.create(
            user=self.user,
            name_account='Zero Account',
            balance=Decimal('0.00'),
            currency='RUB',
        )

        amount = Decimal('100.00')
        with self.assertRaises(ValidationError):
            validate_account_balance(zero_account, amount)

    def test_validate_account_balance_negative_account(self) -> None:
        """Test account balance validation with negative balance account."""
        negative_account = Account.objects.create(
            user=self.user,
            name_account='Negative Account',
            balance=Decimal('-500.00'),
            currency='RUB',
        )

        amount = Decimal('100.00')
        with self.assertRaises(ValidationError):
            validate_account_balance(negative_account, amount)


class TestValidateDifferentAccounts(TestCase):
    """Test cases for validate_different_accounts validator."""

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

    def test_validate_different_accounts_valid(self) -> None:
        """Test different accounts validation with different accounts."""
        validate_different_accounts(self.account1, self.account2)

    def test_validate_different_accounts_same(self) -> None:
        """Test different accounts validation with same account."""
        with self.assertRaises(ValidationError) as context:
            validate_different_accounts(self.account1, self.account1)

        self.assertIn(
            'Нельзя переводить деньги на тот же счет', str(context.exception)
        )

    def test_validate_different_accounts_none_first(self) -> None:
        """Test different accounts validation with None as first account."""
        with self.assertRaises(ValidationError):
            validate_different_accounts(None, self.account2)

    def test_validate_different_accounts_none_second(self) -> None:
        """Test different accounts validation with None as second account."""
        with self.assertRaises(ValidationError):
            validate_different_accounts(self.account1, None)


class TestValidateCreditFieldsRequired(TestCase):
    """Test cases for validate_credit_fields_required validator."""

    def test_validate_credit_fields_required_credit_account(self) -> None:
        """Test credit fields validation for credit account."""
        validate_credit_fields_required(
            type_account=ACCOUNT_TYPE_CREDIT,
            bank='SBERBANK',
            limit_credit=Decimal('10000.00'),
            payment_due_date=timezone.now().date(),
            grace_period_days=30,
        )

    def test_validate_credit_fields_required_credit_card(self) -> None:
        """Test credit fields validation for credit card."""
        validate_credit_fields_required(
            type_account='CREDIT_CARD',
            bank='VTB',
            limit_credit=Decimal('5000.00'),
            payment_due_date=timezone.now().date(),
            grace_period_days=25,
        )

    def test_validate_credit_fields_required_missing_bank(self) -> None:
        """Test credit fields validation with missing bank."""
        with self.assertRaises(ValidationError) as context:
            validate_credit_fields_required(
                type_account=ACCOUNT_TYPE_CREDIT,
                bank=None,
                limit_credit=Decimal('10000.00'),
                payment_due_date=timezone.now().date(),
                grace_period_days=30,
            )

        self.assertIn(
            'Для кредитного счёта необходимо указать банк',
            [str(m) for m in [str(m) for m in context.exception.messages]],
        )

    def test_validate_credit_fields_required_missing_limit(self) -> None:
        """Test credit fields validation with missing limit."""
        with self.assertRaises(ValidationError) as context:
            validate_credit_fields_required(
                type_account=ACCOUNT_TYPE_CREDIT,
                bank='SBERBANK',
                limit_credit=None,
                payment_due_date=timezone.now().date(),
                grace_period_days=30,
            )

        self.assertIn(
            'Для кредитного счёта необходимо указать лимит',
            [str(m) for m in context.exception.messages],
        )

    def test_validate_credit_fields_required_missing_payment_due_date(
        self,
    ) -> None:
        """Test credit fields validation with missing payment due date."""
        with self.assertRaises(ValidationError) as context:
            validate_credit_fields_required(
                type_account=ACCOUNT_TYPE_CREDIT,
                bank='SBERBANK',
                limit_credit=Decimal('10000.00'),
                payment_due_date=None,
                grace_period_days=30,
            )

        self.assertIn(
            'Для кредитного счёта необходимо указать дату платежа',
            [str(m) for m in context.exception.messages],
        )

    def test_validate_credit_fields_required_missing_grace_period(self) -> None:
        """Test credit fields validation with missing grace period."""
        with self.assertRaises(ValidationError) as context:
            validate_credit_fields_required(
                type_account=ACCOUNT_TYPE_CREDIT,
                bank='SBERBANK',
                limit_credit=Decimal('10000.00'),
                payment_due_date=timezone.now().date(),
                grace_period_days=None,
            )

        self.assertIn(
            'Для кредитного счёта необходимо указать льготный период',
            [str(m) for m in context.exception.messages],
        )

    def test_validate_credit_fields_required_multiple_missing(self) -> None:
        """Test credit fields validation with multiple missing fields."""
        with self.assertRaises(ValidationError) as context:
            validate_credit_fields_required(
                type_account=ACCOUNT_TYPE_CREDIT,
                bank=None,
                limit_credit=None,
                payment_due_date=None,
                grace_period_days=None,
            )

        error_messages = [
            str(message) for message in context.exception.messages
        ]
        self.assertIn(
            'Для кредитного счёта необходимо указать банк',
            error_messages,
        )
        self.assertIn(
            'Для кредитного счёта необходимо указать лимит', error_messages
        )
        self.assertIn(
            'Для кредитного счёта необходимо указать дату платежа',
            error_messages,
        )
        self.assertIn(
            'Для кредитного счёта необходимо указать льготный период',
            error_messages,
        )

    def test_validate_credit_fields_required_debit_account(self) -> None:
        """Test credit fields validation for debit account (should pass)."""
        validate_credit_fields_required(
            type_account='Debit',
            bank=None,
            limit_credit=None,
            payment_due_date=None,
            grace_period_days=None,
        )

    def test_validate_credit_fields_required_cash_account(self) -> None:
        """Test credit fields validation for cash account (should pass)."""
        validate_credit_fields_required(
            type_account='CASH',
            bank=None,
            limit_credit=None,
            payment_due_date=None,
            grace_period_days=None,
        )

    def test_validate_credit_fields_required_zero_limit(self) -> None:
        """Test credit fields validation with zero limit."""
        with self.assertRaises(ValidationError) as context:
            validate_credit_fields_required(
                type_account=ACCOUNT_TYPE_CREDIT,
                bank='SBERBANK',
                limit_credit=Decimal('0.00'),
                payment_due_date=timezone.now().date(),
                grace_period_days=30,
            )

        self.assertIn(
            'Для кредитного счёта необходимо указать лимит',
            ''.join(context.exception.messages),
        )

    def test_validate_credit_fields_required_negative_limit(self) -> None:
        """Test credit fields validation with negative limit."""
        with self.assertRaises(ValidationError) as context:
            validate_credit_fields_required(
                type_account=ACCOUNT_TYPE_CREDIT,
                bank='SBERBANK',
                limit_credit=Decimal('-1000.00'),
                payment_due_date=timezone.now().date(),
                grace_period_days=30,
            )

        self.assertIn(
            'Для кредитного счёта необходимо указать лимит',
            ''.join(context.exception.messages),
        )

    def test_validate_credit_fields_required_zero_grace_period(self) -> None:
        """Test credit fields validation with zero grace period."""
        with self.assertRaises(ValidationError) as context:
            validate_credit_fields_required(
                type_account=ACCOUNT_TYPE_CREDIT,
                bank='SBERBANK',
                limit_credit=Decimal('10000.00'),
                payment_due_date=timezone.now().date(),
                grace_period_days=0,
            )

        self.assertIn(
            'Для кредитного счёта необходимо указать льготный период',
            ''.join(context.exception.messages),
        )

    def test_validate_credit_fields_required_negative_grace_period(
        self,
    ) -> None:
        """Test credit fields validation with negative grace period."""
        with self.assertRaises(ValidationError) as context:
            validate_credit_fields_required(
                type_account=ACCOUNT_TYPE_CREDIT,
                bank='SBERBANK',
                limit_credit=Decimal('10000.00'),
                payment_due_date=timezone.now().date(),
                grace_period_days=-5,
            )

        self.assertIn(
            'Для кредитного счёта необходимо указать льготный период',
            ''.join(context.exception.messages),
        )
