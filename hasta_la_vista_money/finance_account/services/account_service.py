"""Service for account management operations."""

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth.models import Group
from django.db.models import QuerySet

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
    GracePeriodInfoDict,
    RaiffeisenbankScheduleDict,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.repositories import ExpenseRepository
    from hasta_la_vista_money.finance_account.repositories import (
        AccountRepository,
        TransferMoneyLogRepository,
    )
    from hasta_la_vista_money.income.repositories import IncomeRepository
    from hasta_la_vista_money.receipts.repositories import ReceiptRepository


class AccountService:
    """Service for account-related operations.

    Handles account management, balance operations, credit card calculations,
    and grace period information.
    """

    def __init__(
        self,
        account_repository: 'AccountRepository',
        transfer_money_log_repository: 'TransferMoneyLogRepository',
        expense_repository: 'ExpenseRepository',
        income_repository: 'IncomeRepository',
        receipt_repository: 'ReceiptRepository',
    ) -> None:
        """Initialize AccountService.

        Args:
            account_repository: Repository for account data access.
            transfer_money_log_repository: Repository for transfer log
                operations.
            expense_repository: Repository for expense data access.
            income_repository: Repository for income data access.
            receipt_repository: Repository for receipt data access.
        """
        self.account_repository = account_repository
        self.transfer_money_log_repository = transfer_money_log_repository

        # Initialize sub-services
        self.balance_service = BalanceService()
        self.credit_calculation_service = CreditCalculationService(
            expense_repository=expense_repository,
            income_repository=income_repository,
            receipt_repository=receipt_repository,
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

    def get_users_for_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> list[User]:
        """Get list of users for a specific group or user.

        Common logic for group filtering used across the application.
        Handles 'my', None, and group ID cases.

        Args:
            user: Current user instance.
            group_id: Optional group ID filter:
                - 'my' or None: return only current user
                - group ID (str): return all users in the group

        Returns:
            List of User instances for the specified group or user.

        Raises:
            Group.DoesNotExist: If group_id is provided but group doesn't
                exist (should be handled by caller).
        """
        if not group_id or group_id == 'my':
            return [user]

        try:
            group = Group.objects.get(pk=group_id)
        except Group.DoesNotExist:
            return []
        else:
            return list(group.user_set.all())

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
        return self.account_repository.get_by_user_and_group(user, group_id)

    def get_sum_all_accounts(self, accounts: QuerySet[Account]) -> Decimal:
        """Calculate total balance for a queryset of accounts.

        Args:
            accounts: QuerySet of accounts to sum.

        Returns:
            Total balance as Decimal.
        """
        total = sum(acc.balance for acc in accounts)
        return Decimal(str(total))

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

    def reconcile_account_balances(
        self,
        old_account: Account,
        new_account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
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
        return self.balance_service.reconcile_account_balances(
            old_account,
            new_account,
            old_total_sum,
            new_total_sum,
        )

    # Credit card calculations - delegated to CreditCalculationService
    def get_credit_card_debt(
        self,
        account: Account,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> Decimal | None:
        """Calculate credit card debt for a given period.

        Calculates the debt by summing expenses and receipts (purchases)
        and subtracting income and returns for the specified period.

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

    def calculate_grace_period_info(
        self,
        account: Account,
        purchase_month: date | datetime,
    ) -> GracePeriodInfoDict:
        """Calculate grace period information for a credit card.

        Args:
            account: Credit card account.
            purchase_month: Month to calculate grace period for.

        Returns:
            Dictionary with grace period information. Empty dict if account
            is not a credit card.
        """
        return self.credit_calculation_service.calculate_grace_period_info(
            account,
            purchase_month,
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
