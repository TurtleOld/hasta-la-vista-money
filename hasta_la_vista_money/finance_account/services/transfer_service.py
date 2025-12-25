from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_different_accounts,
    validate_positive_amount,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.repositories import (
        TransferMoneyLogRepository,
    )


class TransferService:
    """Service for handling money transfers between accounts.

    This service handles money transfers between user accounts with validation,
    balance updates, and transaction logging.
    """

    def __init__(
        self,
        transfer_money_log_repository: 'TransferMoneyLogRepository',
    ) -> None:
        """Initialize TransferService.

        Args:
            transfer_money_log_repository: Repository for transfer log
                operations.
        """
        self.transfer_money_log_repository = transfer_money_log_repository

    @transaction.atomic
    def transfer_money(
        self,
        from_account: Account,
        to_account: Account,
        amount: Decimal,
        user: User,
        exchange_date: datetime | None = None,
        notes: str | None = None,
    ) -> TransferMoneyLog:
        """Transfer money between accounts with validation and logging.

        Args:
            from_account: Source account for the transfer.
            to_account: Destination account for the transfer.
            amount: Amount to transfer. Must be positive.
            user: User performing the transfer.
            exchange_date: Optional exchange date for the transfer.
            notes: Optional notes for the transfer.

        Returns:
            TransferMoneyLog: Created transfer log entry.

        Raises:
            ValueError: If transfer fails due to insufficient funds or
                invalid accounts.
        """
        validate_positive_amount(amount)
        validate_different_accounts(from_account, to_account)
        validate_account_balance(from_account, amount)

        if from_account.transfer_money(to_account, amount):
            return self.transfer_money_log_repository.create_log(
                user=user,
                from_account=from_account,
                to_account=to_account,
                amount=amount,
                exchange_date=exchange_date,
                notes=notes or '',
            )

        error_msg = 'Transfer failed - insufficient funds or invalid accounts'
        raise ValueError(error_msg)
