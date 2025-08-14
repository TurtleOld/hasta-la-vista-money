"""
Validators for finance account forms.

This module contains custom validators for account-related forms,
separating business logic validation from form definitions.
"""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account


def validate_account_balance(from_account: Account, amount: Decimal) -> None:
    """
    Validate that the account has sufficient balance for the transfer.

    Args:
        from_account: The source account for the transfer
        amount: The amount to transfer

    Raises:
        ValidationError: If insufficient funds
    """
    if amount > from_account.balance:
        raise ValidationError(
            constants.SUCCESS_MESSAGE_INSUFFICIENT_FUNDS, code='insufficient_funds'
        )


def validate_different_accounts(from_account: Account, to_account: Account) -> None:
    """
    Validate that source and destination accounts are different.

    Args:
        from_account: The source account
        to_account: The destination account

    Raises:
        ValidationError: If accounts are the same
    """
    if from_account == to_account:
        raise ValidationError(constants.ANOTHER_ACCRUAL_ACCOUNT, code='same_accounts')


def validate_credit_fields_required(
    type_account: str,
    bank: str,
    limit_credit: Any = None,
    payment_due_date: Any = None,
    grace_period_days: Any = None,
) -> None:
    """
    Validate that credit-related fields are provided for credit accounts.

    Args:
        type_account: The type of account
        limit_credit: Credit limit value
        payment_due_date: Payment due date
        grace_period_days: Grace period in days

    Raises:
        ValidationError: If credit fields are missing for credit accounts
    """
    credit_types = ['Credit', 'CreditCard']

    if type_account in credit_types:
        if not limit_credit:
            raise ValidationError(
                _('Кредитный лимит обязателен для кредитных счетов'),
                code='credit_limit_required',
            )
        if not bank:
            raise ValidationError(
                _('Банк обязателен для кредитных счетов'),
                code='bank_required',
            )
        if not payment_due_date:
            raise ValidationError(
                _('Дата платежа обязательна для кредитных счетов'),
                code='payment_due_date_required',
            )
        if not grace_period_days:
            raise ValidationError(
                _('Льготный период обязателен для кредитных счетов'),
                code='grace_period_required',
            )


def validate_positive_amount(amount: Decimal) -> None:
    """
    Validate that the amount is positive.

    Args:
        amount: The amount to validate

    Raises:
        ValidationError: If amount is not positive
    """
    if amount <= 0:
        raise ValidationError(_('Сумма должна быть больше нуля'), code='invalid_amount')
