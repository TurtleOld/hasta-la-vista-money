"""Tests for the receipts API validator."""

from decimal import Decimal

from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.receipts.validators.receipt_api_validator import (
    ReceiptAPIValidator,
)
from hasta_la_vista_money.users.models import User


class TestReceiptAPIValidatorAccountSelection(TestCase):
    """The validator must only accept accounts open for regular operations."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='validator-user',
            password='testpass123',  # nosec B106: test-only password
        )
        self.bank = Bank.objects.get(code='SBERBANK')
        self.validator = ReceiptAPIValidator()

    def test_regular_account_is_accepted(self) -> None:
        account = Account.objects.create(
            user=self.user,
            name_account='Regular',
            balance=Decimal('100.00'),
            currency='RUB',
            type_account='Debit',
            bank=self.bank,
        )

        result = self.validator.validate_user_and_account(
            self.user.pk,
            account.pk,
        )

        self.assertTrue(result.is_valid, result.error)
        self.assertEqual(result.account, account)

    def test_deposit_account_is_rejected(self) -> None:
        deposit = Account.objects.create_deposit(
            user=self.user,
            name_account='Deposit',
            balance=Decimal('100.00'),
            currency='RUB',
            bank=self.bank,
        )

        result = self.validator.validate_user_and_account(
            self.user.pk,
            deposit.pk,
        )

        self.assertFalse(result.is_valid)
        self.assertIsNone(result.account)
