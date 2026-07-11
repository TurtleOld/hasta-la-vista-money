from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.finance_account.validators import (
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
        self._balance_service = BalanceService()

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
        if from_account.user_id != user.pk or to_account.user_id != user.pk:
            raise PermissionDenied(
                _('У вас нет прав на операции с этими счетами.'),
            )

        locked_accounts = self._balance_service.apply_account_deltas(
            {
                from_account.pk: -amount,
                to_account.pk: amount,
            },
        )
        from_account = locked_accounts[from_account.pk]
        to_account = locked_accounts[to_account.pk]

        return self.transfer_money_log_repository.create_log(
            user=user,
            from_account=from_account,
            to_account=to_account,
            amount=amount,
            exchange_date=exchange_date,
            notes=notes or '',
        )

    def get_last_used_accounts(
        self,
        user: User,
    ) -> tuple[Account | None, Account | None]:
        """Return the account pair from the user's latest transfer."""
        latest_transfer = (
            self.transfer_money_log_repository.get_latest_by_user_with_accounts(
                user,
            )
        )
        if latest_transfer is None:
            return None, None
        return latest_transfer.from_account, latest_transfer.to_account

    @transaction.atomic
    def delete_transfer(
        self,
        *,
        transfer_id: int,
        user: User,
    ) -> None:
        """Delete transfer log and reverse its balance movements.

        Raises:
            PermissionDenied: If the transfer does not belong to the user.
            ValidationError: If one of transfer accounts was already deleted.
        """
        try:
            transfer_log = (
                self.transfer_money_log_repository.get_by_id_for_user(
                    transfer_id,
                    user,
                    for_update=True,
                )
            )
        except TransferMoneyLog.DoesNotExist as error:
            raise PermissionDenied(
                _('Перевод не найден или недоступен.'),
            ) from error

        if transfer_log.from_account is None or transfer_log.to_account is None:
            raise ValidationError(
                _(
                    'Нельзя удалить перевод: один из счетов уже удалён.',
                ),
            )

        self._balance_service.apply_account_deltas(
            {
                transfer_log.from_account.pk: transfer_log.amount,
                transfer_log.to_account.pk: -transfer_log.amount,
            },
        )
        self.transfer_money_log_repository.delete_log(transfer_log)
