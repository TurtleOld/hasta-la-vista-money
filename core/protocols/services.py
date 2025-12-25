from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from django.db.models import QuerySet

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import (
        Account,
        TransferMoneyLog,
    )
    from hasta_la_vista_money.finance_account.services import (
        GracePeriodInfoDict,
        RaiffeisenbankScheduleDict,
    )


@runtime_checkable
class AccountServiceProtocol(Protocol):
    """Protocol for account service operations.

    Defines interface for account-related operations including balance
    management, credit card calculations, and user group handling.
    """

    def get_user_accounts(self, user: User) -> list['Account']:
        """Get all accounts for a user.

        Args:
            user: User to get accounts for.

        Returns:
            List of Account instances.
        """
        ...

    def get_account_by_id(
        self, account_id: int, user: User
    ) -> Optional['Account']:
        """Get account by ID for a user.

        Args:
            account_id: Account ID.
            user: User to verify ownership.

        Returns:
            Account instance if found and owned, None otherwise.
        """
        ...

    def get_credit_card_debt(
        self,
        account: 'Account',
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> Decimal | None:
        """Calculate credit card debt for a period.

        Args:
            account: Credit card account.
            start_date: Optional start date.
            end_date: Optional end date.

        Returns:
            Debt amount or None if not a credit account.
        """
        ...

    def calculate_grace_period_info(
        self,
        account: 'Account',
        purchase_month: date | datetime,
    ) -> 'GracePeriodInfoDict':
        """Calculate grace period information.

        Args:
            account: Credit card account.
            purchase_month: Month to calculate for.

        Returns:
            Dictionary with grace period information.
        """
        ...

    def calculate_raiffeisenbank_payment_schedule(
        self,
        account: 'Account',
        purchase_month: date | datetime,
    ) -> 'RaiffeisenbankScheduleDict':
        """Calculate Raiffeisenbank payment schedule.

        Args:
            account: Raiffeisenbank credit card account.
            purchase_month: Month to calculate for.

        Returns:
            Dictionary with payment schedule information.
        """
        ...

    def apply_receipt_spend(
        self, account: 'Account', amount: Decimal
    ) -> 'Account':
        """Apply spending to account balance.

        Args:
            account: Account to charge.
            amount: Amount to subtract.

        Returns:
            Updated Account instance.
        """
        ...

    def refund_to_account(
        self, account: 'Account', amount: Decimal
    ) -> 'Account':
        """Refund amount to account balance.

        Args:
            account: Account to refund to.
            amount: Amount to add.

        Returns:
            Updated Account instance.
        """
        ...

    def reconcile_account_balances(
        self,
        old_account: 'Account',
        new_account: 'Account',
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """Reconcile account balances when transaction changes.

        Args:
            old_account: Account before change.
            new_account: Account after change.
            old_total_sum: Amount before change.
            new_total_sum: Amount after change.
        """
        ...

    def get_transfer_money_log(
        self,
        user: User,
        limit: int = constants.TRANSFER_MONEY_LOG_LIMIT,
    ) -> QuerySet['TransferMoneyLog']:
        """Get transfer logs for a user.

        Args:
            user: User to get logs for.
            limit: Maximum number of logs.

        Returns:
            QuerySet of transfer logs.
        """
        ...

    def get_users_for_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> list[User]:
        """Get users for a group or user.

        Args:
            user: Current user.
            group_id: Optional group ID.

        Returns:
            List of User instances.
        """
        ...

    def get_accounts_for_user_or_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> QuerySet['Account']:
        """Get accounts for user or group.

        Args:
            user: User instance.
            group_id: Optional group ID.

        Returns:
            QuerySet of accounts.
        """
        ...

    def get_sum_all_accounts(self, accounts: QuerySet['Account']) -> Decimal:
        """Calculate total balance for accounts.

        Args:
            accounts: QuerySet of accounts to sum.

        Returns:
            Total balance as Decimal.
        """
        ...
