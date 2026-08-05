from typing import Protocol

from django.db.models import QuerySet

from hasta_la_vista_money.deposits.commands import (
    AddFloatingRatePeriodCommand,
    CapitalizeInterestCommand,
    CloseDepositEarlyCommand,
    CloseMaturedDepositCommand,
    CloseMaturedDepositResult,
    ConfirmInterestPaymentCommand,
    ConvertAccountToDepositCommand,
    CreateDepositCommand,
    ForecastEarlyClosureCommand,
    ForecastEarlyClosureResult,
    FundDepositCommand,
    OpenExistingDepositCommand,
    RecalculateInterestForecastCommand,
    RenewDepositCommand,
    TopUpDepositCommand,
)
from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositCapitalizationEvent,
    DepositInterestForecast,
    DepositPrincipalEvent,
    DepositRatePeriod,
    DepositTerm,
)
from hasta_la_vista_money.users.models import User


class DepositServiceProtocol(Protocol):
    def open_existing_term_deposit(
        self,
        command: OpenExistingDepositCommand,
    ) -> Deposit:
        """Record an already-active term deposit via a neutral opening position.

        Args:
            command: Details of the existing deposit to record.

        Returns:
            The created Deposit with an immutable opening-position event.
        """

    def create_funded_term_deposit(
        self,
        command: FundDepositCommand,
    ) -> Deposit:
        """Fund a new term deposit by transferring from an owned source account.

        Args:
            command: Funding details including source account and amount.

        Returns:
            The created Deposit with an immutable funding event.

        Raises:
            ValidationError: If the source account is invalid or insufficient.
        """

    def create_term_deposit(
        self,
        command: CreateDepositCommand,
    ) -> Deposit:
        """Create a term deposit with its initial balance.

        Args:
            command: Deposit creation parameters.

        Returns:
            The created Deposit.
        """

    def convert_account_to_deposit(
        self,
        command: ConvertAccountToDepositCommand,
    ) -> Deposit:
        """Convert an existing production account into a term deposit.

        Args:
            command: Account identifier, agreement parameters, and the
                conversion date.

        Returns:
            The created Deposit, wrapping the same account.

        Raises:
            ValidationError: If the account is invalid, already a deposit,
                already linked, or the agreement parameters are invalid.
        """

    def add_floating_rate_period(
        self,
        command: AddFloatingRatePeriodCommand,
    ) -> DepositRatePeriod:
        """Append a new effective-rate period to a floating-rate term.

        Args:
            command: Term identifier, new period's start date, rate, and
                note.

        Returns:
            The newly created DepositRatePeriod.

        Raises:
            ValidationError: If the term is invalid, not floating, matured,
                or the new period's parameters are invalid.
        """

    def get_user_deposits(self, user: User) -> QuerySet[Deposit]: ...

    def get_user_deposit(self, deposit_id: int, user: User) -> Deposit: ...

    def recalculate_forecast(
        self,
        command: RecalculateInterestForecastCommand,
    ) -> list[DepositInterestForecast]:
        """Rebuild a term's expected interest payout forecast.

        Args:
            command: Term identifier to recalculate the forecast for.

        Returns:
            The newly created forecast lines, in chronological order.

        Raises:
            ValidationError: If the term is invalid or not owned, or the
            custom payout schedule has no configured dates.
        """

    def renew_matured_deposit(
        self,
        command: RenewDepositCommand,
    ) -> DepositTerm: ...

    def is_renewal_available(self, deposit: Deposit) -> bool: ...

    def top_up_deposit_principal(
        self,
        command: TopUpDepositCommand,
    ) -> DepositPrincipalEvent: ...

    def capitalize_interest(
        self,
        command: CapitalizeInterestCommand,
    ) -> DepositCapitalizationEvent: ...

    def confirm_interest_payment(
        self,
        command: ConfirmInterestPaymentCommand,
    ) -> DepositCapitalizationEvent: ...

    def close_matured_deposit(
        self,
        command: CloseMaturedDepositCommand,
    ) -> CloseMaturedDepositResult: ...

    def forecast_early_closure(
        self,
        command: ForecastEarlyClosureCommand,
    ) -> ForecastEarlyClosureResult: ...

    def close_deposit_early(
        self,
        command: CloseDepositEarlyCommand,
    ) -> CloseMaturedDepositResult: ...
