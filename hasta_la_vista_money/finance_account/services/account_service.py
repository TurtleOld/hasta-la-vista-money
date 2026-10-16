"""Service for account management operations."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction as db_transaction
from django.db.models import ProtectedError, QuerySet, Sum
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.finance_account.services.credit_calculation_service import (  # noqa: E501
    CreditCalculationService,
)
from hasta_la_vista_money.finance_account.services.types import (
    BalanceReconcileCommand,
    RaiffeisenbankScheduleDict,
)
from hasta_la_vista_money.system.models import AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.groups import (
    readable_users,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.repositories import (
        AccountRepository,
        TransferMoneyLogRepository,
    )
    from hasta_la_vista_money.receipts.repositories import ReceiptRepository
    from hasta_la_vista_money.transactions.repositories.transaction_repository import (  # noqa: E501
        TransactionRepository,
    )


class AccountService:
    """Service for account-related operations.

    Handles account management, balance operations, credit card calculations,
    and grace period information.
    """

    def __init__(
        self,
        account_repository: 'AccountRepository',
        transfer_money_log_repository: 'TransferMoneyLogRepository',
        transaction_repository: 'TransactionRepository',
        receipt_repository: 'ReceiptRepository',
    ) -> None:
        """Initialize AccountService.

        Args:
            account_repository: Repository for account data access.
            transfer_money_log_repository: Repository for transfer log
                operations.
            transaction_repository: Repository for transaction data access.
            receipt_repository: Repository for receipt data access.
        """
        self.account_repository = account_repository
        self.transfer_money_log_repository = transfer_money_log_repository

        # Initialize sub-services
        self.balance_service = BalanceService()
        self.credit_calculation_service = CreditCalculationService(
            transaction_repository=transaction_repository,
            receipt_repository=receipt_repository,
            transfer_money_log_repository=transfer_money_log_repository,
        )

    def get_user_accounts(self, user: User) -> list[Account]:
        """Get all accounts for a specific user.

        Args:
            user: User instance to get accounts for.

        Returns:
            List of Account instances for the user.
        """
        return list(self.account_repository.get_by_user_with_related(user))

    def get_account_by_id(self, account_id: int, user: User) -> Account | None:
        """Get a specific account by ID for a user.

        Args:
            account_id: ID of the account to retrieve.
            user: User instance to verify ownership.

        Returns:
            Account instance if found and owned by user, None otherwise.
        """
        return self.account_repository.get_by_id_and_user(account_id, user)

    def get_accounts_for_user_or_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> QuerySet[Account]:
        """Get accounts for user or group.

        Args:
            user: User instance.
            group_id: Optional group ID filter.

        Returns:
            QuerySet of accounts for user or group.
        """
        return self.account_repository.get_by_users(
            readable_users(user, group_id),
        )

    def get_balances_by_currency(
        self,
        accounts: QuerySet[Account],
    ) -> dict[str, Decimal]:
        """Calculate account balances grouped by currency.

        Args:
            accounts: QuerySet of accounts to sum.

        Returns:
            Account balance keyed by currency code.
        """
        return {
            str(row['currency']): Decimal(row['total'] or constants.ZERO)
            for row in accounts.values('currency')
            .annotate(total=Sum('balance'))
            .order_by('currency')
        }

    def get_transfer_money_log(
        self,
        user: User,
        limit: int = constants.TRANSFER_MONEY_LOG_LIMIT,
    ) -> QuerySet[TransferMoneyLog]:
        """Get recent transfer logs for a user.

        Args:
            user: User to get transfer logs for.
            limit: Maximum number of logs to return.

        Returns:
            QuerySet of transfer logs ordered by date descending.
        """
        return self.transfer_money_log_repository.get_by_user_ordered(
            user,
            limit,
        )

    def _lock_regular_account(self, user: User, account_id: int) -> Account:
        """Lock an own non-deposit account inside the caller's transaction."""
        account = self.account_repository.get_by_ids_for_update(
            {account_id},
        ).get(account_id)
        if account is None or account.user_id != user.pk:
            raise PermissionDenied(
                _('У вас нет прав на операции с этим счётом.'),
            )
        if account.is_deposit:
            raise ValidationError(
                constants.ACCOUNT_DEPOSIT_MANAGED_BY_DEPOSIT_MESSAGE,
            )
        return account

    def archive_account(self, *, user: User, account_id: int) -> None:
        """Archive an own regular account with a zero balance."""
        with db_transaction.atomic():
            account = self._lock_regular_account(user, account_id)
            if account.balance:
                raise ValidationError(
                    constants.ACCOUNT_ARCHIVE_NONZERO_BALANCE_MESSAGE,
                )
            with audit_operation(kind=AuditOperationKind.ACCOUNT_EDIT):
                self.account_repository.archive(account.pk)

    def unarchive_account(self, *, user: User, account_id: int) -> None:
        """Return an own regular account from the archive."""
        with db_transaction.atomic():
            account = self._lock_regular_account(user, account_id)
            with audit_operation(kind=AuditOperationKind.ACCOUNT_EDIT):
                self.account_repository.unarchive(account.pk)

    def delete_account(self, *, user: User, account_id: int) -> None:
        """Delete an own regular account that has no movements."""
        with db_transaction.atomic():
            account = self._lock_regular_account(user, account_id)
            if account.has_movements():
                raise ValidationError(constants.ACCOUNT_HAS_MOVEMENTS_MESSAGE)
            try:
                with audit_operation(kind=AuditOperationKind.ACCOUNT_DELETE):
                    account.delete()
            except ProtectedError as error:
                # A movement landed after the check: the DB still protects it.
                raise ValidationError(
                    constants.ACCOUNT_HAS_MOVEMENTS_MESSAGE,
                ) from error

    # Balance operations - delegated to BalanceService
    def apply_receipt_spend(self, account: Account, amount: Decimal) -> Account:
        """Apply spending by receipt to the account balance.

        Args:
            account: Account to apply spending to.
            amount: Amount to subtract from balance. Must be positive.

        Returns:
            Updated Account instance.

        Raises:
            ValidationError: If amount is invalid or account has
                insufficient funds.
        """
        return self.balance_service.apply_receipt_spend(account, amount)

    def refund_to_account(self, account: Account, amount: Decimal) -> Account:
        """Return money to account balance.

        Args:
            account: Account to refund to.
            amount: Amount to add to balance. Must be positive.

        Returns:
            Updated Account instance.

        Raises:
            ValidationError: If amount is invalid.
        """
        return self.balance_service.refund_to_account(account, amount)

    def apply_account_deltas(
        self,
        deltas: dict[int, Decimal],
    ) -> dict[int, Account]:
        """Apply signed balance deltas atomically."""
        return self.balance_service.apply_account_deltas(deltas)

    def reconcile_account_balances(
        self,
        command: BalanceReconcileCommand,
    ) -> None:
        """Reconcile account balances when amount or account changes.

        Handles two scenarios:
        1. Same account: adjusts balance by difference
        2. Different accounts: refunds old account, applies to new account

        Args:
            old_account: Account before change.
            new_account: Account after change.
            old_total_sum: Total amount before change.
            new_total_sum: Total amount after change.
        """
        return self.balance_service.reconcile_account_balances(command)

    # Credit card calculations - delegated to CreditCalculationService
    def get_credit_card_debt(
        self,
        account: Account,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> Decimal | None:
        """Calculate credit card debt for a given period.

        Calculates the period-scoped debt by summing expenses and receipts
        (purchases) and subtracting income and returns within the period.
        This is not the total card debt: that is the credit limit minus the
        account balance (see ``card_debt_for_balance``).

        Args:
            account: Account instance. Must be credit card or credit type.
            start_date: Optional start date for the period.
            end_date: Optional end date for the period.

        Returns:
            Decimal debt amount if account is credit type, None otherwise.
        """
        return self.credit_calculation_service.get_credit_card_debt(
            account,
            start_date,
            end_date,
        )

    def calculate_raiffeisenbank_payment_schedule(
        self,
        account: Account,
        purchase_month: date | datetime,
    ) -> RaiffeisenbankScheduleDict:
        """Calculate payment schedule for Raiffeisenbank credit card.

        Args:
            account: Raiffeisenbank credit card account.
            purchase_month: Month to calculate schedule for.

        Returns:
            Dictionary with payment schedule information. Empty dict if
            account is not eligible.
        """
        service = self.credit_calculation_service
        return service.calculate_raiffeisenbank_payment_schedule(
            account,
            purchase_month,
        )
