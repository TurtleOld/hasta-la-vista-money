"""Protocols for finance account services."""

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services.types import (
    BalanceReconcileCommand,
    BalanceTrendData,
    FinancialMovement,
    RaiffeisenbankScheduleDict,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from hasta_la_vista_money.users.models import User


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

        Period-scoped debt; the total card debt is the credit limit minus
        the account balance.

        Args:
            account: Account instance. Must be credit card or credit type.
            start_date: Optional start date for the period.
            end_date: Optional end date for the period.

        Returns:
            Decimal debt amount if account is credit type, None otherwise.
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
        command: BalanceReconcileCommand,
    ) -> None:
        """Reconcile account balances when amount or account changes.

        Args:
            old_account: Account before change.
            new_account: Account after change.
            old_total_sum: Total amount before change.
            new_total_sum: Total amount after change.
        """
        ...


@runtime_checkable
class FinancialMovementSourceProtocol(Protocol):
    """Protocol for a domain that owns balance-affecting events other than
    Receipt, Transaction, and TransferMoneyLog.

    `finance_account` does not import the owning domain's models directly;
    each source translates its own events into normalized
    `FinancialMovement` values on request.
    """

    def list_financial_movements(
        self,
        accounts: Sequence[Account],
        since: date,
    ) -> list[FinancialMovement]:
        """List this domain's balance-affecting events for the accounts.

        Each movement's delta is its net effect on the accounts together.

        Args:
            accounts: Accounts to list movements for.
            since: Only movements effective on or after this date.

        Returns:
            Normalized movements, in no particular order.
        """
        ...


class AnalyticsCurrencyServiceProtocol(Protocol):
    """Pick the one currency analytics pages show."""

    def available_currencies(self, users: Iterable['User']) -> list[str]:
        """Currencies of the users' accounts, first account's first."""
        ...

    def resolve(
        self,
        request_value: str | None,
        session_value: str | None,
        available: Sequence[str],
    ) -> str:
        """Request, then session, then RUB, then first available currency.

        Values outside ``available`` are ignored.
        """
        ...


class BalanceHistoryServiceProtocol(Protocol):
    """Reconstruct account balances at past moments."""

    def balance_at(self, account: Account, moment: datetime) -> Decimal:
        """Account balance immediately after `moment`."""
        ...

    def daily_balances(
        self,
        accounts: Sequence[Account],
        start: date,
        end: date,
    ) -> dict[date, Decimal]:
        """Summed end-of-day balance of `accounts`, `start` to `end`."""
        ...


class BalanceTrendServiceProtocol(Protocol):
    """Daily balance trend of one currency's accounts."""

    def get_balance_trend(
        self,
        accounts: 'QuerySet[Account]',
        currency: str,
        period: str = '30d',
    ) -> BalanceTrendData:
        """Current balance, delta and daily series for `period`."""
        ...
