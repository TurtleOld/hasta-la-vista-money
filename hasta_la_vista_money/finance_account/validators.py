"""Validators for finance account forms.

This module contains custom validators for account-related forms,
separating business logic validation from form definitions. Includes
validation for account balances, credit field requirements, and transfer
operations.
"""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT,
    ACCOUNT_TYPE_CREDIT_CARD,
)
from hasta_la_vista_money.finance_account.models import Account


def validate_account_balance(from_account: Account, amount: Decimal) -> None:
    """Validate that the account has sufficient balance for the transfer.

    Checks if the source account has enough funds to complete the transfer
    operation without going into negative balance.

    Args:
        from_account: The source account for the transfer.
        amount: The amount to transfer.

    Raises:
        ValidationError: If insufficient funds are available.
    """
    if amount > from_account.balance:
        raise ValidationError(
            _('Недостаточно средств на счете'),
            code='insufficient_funds',
        )


def validate_different_accounts(
    from_account: Account,
    to_account: Account,
) -> None:
    """Validate that source and destination accounts are different.

    Ensures that money transfers occur between different accounts to prevent
    circular or meaningless transfer operations.

    Args:
        from_account: The source account.
        to_account: The destination account.

    Raises:
        ValidationError: If source and destination accounts are the same.
    """
    if from_account is None or to_account is None:
        raise ValidationError(
            _('Нельзя выбирать одинаковые счета для перевода.'),
            code='invalid_accounts',
        )
    if from_account == to_account:
        raise ValidationError(
            _('Нельзя переводить деньги на тот же счет'),
            code='same_accounts',
        )


def validate_credit_fields_required(
    type_account: str,
    bank: str,
    limit_credit: Any = None,
    payment_due_date: Any = None,
    grace_period_days: Any = None,
) -> None:
    """Validate that credit-related fields are provided for credit accounts.

    Ensures that all required fields are present when creating or updating
    credit accounts, including bank information, credit limits,
    and payment terms.

    Args:
        type_account: The type of account (Credit or CreditCard).
        bank: The bank issuing the credit account.
        limit_credit: Credit limit value.
        payment_due_date: Payment due date.
        grace_period_days: Grace period in days.

    Raises:
        ValidationError: If credit fields are missing for credit accounts.
    """
    credit_types = [ACCOUNT_TYPE_CREDIT, ACCOUNT_TYPE_CREDIT_CARD]

    if type_account in credit_types:
        errors = []

        if not bank or bank == '-':
            errors.append(_('Для кредитного счёта необходимо указать банк'))

        if not limit_credit or limit_credit <= 0:
            errors.append(_('Для кредитного счёта необходимо указать лимит'))

        if not payment_due_date:
            errors.append(
                _('Для кредитного счёта необходимо указать дату платежа')
            )

        if not grace_period_days or grace_period_days <= 0:
            errors.append(
                _('Для кредитного счёта необходимо указать льготный период')
            )

        if errors:
            raise ValidationError(errors)


def validate_positive_amount(amount: Decimal) -> None:
    """Validate that the amount is positive.

    Ensures that financial amounts are greater than zero to prevent
    invalid or meaningless financial operations.

    Args:
        amount: The amount to validate.

    Raises:
        ValidationError: If amount is zero or negative.
    """
    if amount <= 0:
        raise ValidationError(
            _('Сумма должна быть больше нуля'),
            code='invalid_amount',
        )
