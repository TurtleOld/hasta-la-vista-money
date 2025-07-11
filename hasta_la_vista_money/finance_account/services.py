"""
Services for finance account operations.

This module contains business logic for account operations,
separating it from form and view logic.
"""

from decimal import Decimal
from typing import Optional

from django.db import transaction
from hasta_la_vista_money.finance_account.models import Account, TransferMoneyLog
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_different_accounts,
    validate_positive_amount,
)
from hasta_la_vista_money.users.models import User


class TransferService:
    """Service for handling money transfers between accounts."""

    @staticmethod
    @transaction.atomic
    def transfer_money(
        from_account: Account,
        to_account: Account,
        amount: Decimal,
        user: User,
        exchange_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> TransferMoneyLog:
        """
        Transfer money between accounts with validation and logging.

        Args:
            from_account: Source account
            to_account: Destination account
            amount: Transfer amount
            user: User performing the transfer
            exchange_date: Transfer date (optional)
            notes: Transfer notes (optional)

        Returns:
            TransferMoneyLog: Created transfer log entry

        Raises:
            ValueError: If transfer fails
        """
        # Validate transfer parameters
        validate_positive_amount(amount)
        validate_different_accounts(from_account, to_account)
        validate_account_balance(from_account, amount)

        # Perform the transfer
        if from_account.transfer_money(to_account, amount):
            # Create transfer log
            transfer_log = TransferMoneyLog.objects.create(
                user=user,
                from_account=from_account,
                to_account=to_account,
                amount=amount,
                exchange_date=exchange_date,
                notes=notes or "",
            )
            return transfer_log

        raise ValueError("Transfer failed - insufficient funds or invalid accounts")


class AccountService:
    """Service for account-related operations."""

    @staticmethod
    def get_user_accounts(user: User) -> list[Account]:
        """
        Get all accounts for a specific user.

        Args:
            user: User whose accounts to retrieve

        Returns:
            List of user's accounts
        """
        return list(Account.objects.filter(user=user).select_related("user"))

    @staticmethod
    def get_account_by_id(account_id: int, user: User) -> Optional[Account]:
        """
        Get a specific account by ID for a user.

        Args:
            account_id: Account ID
            user: User who owns the account

        Returns:
            Account instance or None if not found
        """
        try:
            return Account.objects.get(id=account_id, user=user)
        except Account.DoesNotExist:
            return None
