"""Protocols for finance account services."""

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services.types import (
    GracePeriodInfoDict,
    RaiffeisenbankScheduleDict,
)


@runtime_checkable
class BankCalculatorProtocol(Protocol):
    """Protocol for bank-specific credit card calculators.

    Defines interface for calculating grace periods and payment schedules
    for different banks.
    """

    def calculate_grace_period(
        self,
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate grace period for the bank.

        Args:
            account: Account to calculate grace period for.
            purchase_start: Start of purchase period.
            purchase_end: End of purchase period.

        Returns:
            Tuple of (grace_end, payments_start, payments_end) datetimes.
        """
        ...


@runtime_checkable
class CreditCalculationServiceProtocol(Protocol):
    """Protocol for credit card calculation service.

    Defines interface for credit card debt and grace period calculations.
    """

    def get_credit_card_debt(
        self,
        account: Account,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> Decimal | None:
        """Calculate credit card debt for a given period.

        Args:
            account: Account instance. Must be credit card or credit type.
            start_date: Optional start date for the period.
            end_date: Optional end date for the period.

        Returns:
            Decimal debt amount if account is credit type, None otherwise.
        """
        ...

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
        ...

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
        ...


@runtime_checkable
class BalanceServiceProtocol(Protocol):
    """Protocol for balance operations service.

    Defines interface for account balance operations.
    """

    def apply_receipt_spend(self, account: Account, amount: Decimal) -> Account:
        """Apply spending by receipt to the account balance.

        Args:
            account: Account to apply spending to.
            amount: Amount to subtract from balance. Must be positive.

        Returns:
            Updated Account instance.
        """
        ...

    def refund_to_account(self, account: Account, amount: Decimal) -> Account:
        """Return money to account balance.

        Args:
            account: Account to refund to.
            amount: Amount to add to balance. Must be positive.

        Returns:
            Updated Account instance.
        """
        ...

    def reconcile_account_balances(
        self,
        old_account: Account,
        new_account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """Reconcile account balances when amount or account changes.

        Args:
            old_account: Account before change.
            new_account: Account after change.
            old_total_sum: Total amount before change.
            new_total_sum: Total amount after change.
        """
        ...
