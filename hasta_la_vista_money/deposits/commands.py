from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from hasta_la_vista_money.deposits.models import (
    DepositCapitalizationEvent,
    DepositTerm,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import Bank


@dataclass(frozen=True)
class ForecastTerms:
    """Contract terms governing a term's expected-payout forecast.

    Purely configuration — never affects Account.balance or actual
    income/expense. Defaults match the previous fixed behaviour (single
    payout at maturity, Actual/Actual, no business-day roll).
    """

    day_count_convention: str = DepositTerm.DayCountConvention.ACTUAL_ACTUAL
    accrual_start_included: bool = True
    accrual_end_included: bool = False
    payout_schedule_kind: str = DepositTerm.PayoutScheduleKind.MATURITY
    custom_payout_dates: list[date] = field(default_factory=list)
    business_day_convention: str = DepositTerm.BusinessDayConvention.NONE
    interest_payout_destination: str = (
        DepositTerm.PayoutDestination.CAPITALIZATION
    )


@dataclass(frozen=True)
class WithdrawalTerms:
    withdrawal_allowed: bool = False
    minimum_withdrawal_amount: Decimal | None = None
    maximum_withdrawal_amount: Decimal | None = None
    withdrawal_deadline: date | None = None
    minimum_balance: Decimal = Decimal()


@dataclass(frozen=True)
class TopUpTerms:
    top_up_allowed: bool = False
    minimum_top_up_amount: Decimal | None = None
    maximum_top_up_amount: Decimal | None = None
    top_up_deadline: date | None = None
    maximum_balance: Decimal | None = None


@dataclass(frozen=True)
class CreateDepositCommand:
    user: User
    name: str
    bank: 'str | Bank'
    currency: str
    balance: Decimal
    opened_on: date
    matures_on: date
    annual_rate: Decimal
    rate_kind: str
    forecast_terms: ForecastTerms = field(default_factory=ForecastTerms)
    withdrawal_terms: WithdrawalTerms = field(default_factory=WithdrawalTerms)
    top_up_terms: TopUpTerms = field(default_factory=TopUpTerms)


@dataclass(frozen=True)
class FundDepositCommand:
    """Command to fund a new term deposit from an owned source account.

    The source account must belong to the user and be in the same currency.
    The funding is executed as a financially neutral internal transfer.
    """

    user: User
    name: str
    bank: 'str | Bank'
    currency: str
    amount: Decimal
    source_account_id: int
    opened_on: date
    matures_on: date
    annual_rate: Decimal
    rate_kind: str
    forecast_terms: ForecastTerms = field(default_factory=ForecastTerms)
    withdrawal_terms: WithdrawalTerms = field(default_factory=WithdrawalTerms)
    top_up_terms: TopUpTerms = field(default_factory=TopUpTerms)


@dataclass(frozen=True)
class ConvertAccountToDepositCommand:
    """Command to convert an existing production account into a deposit.

    The account keeps its PK, balance, currency, owner, and timestamps.
    The account type changes to Deposit, a deposit agreement, term, and
    rate period are created, and a neutral opening-position event is
    recorded on the conversion date — no monetary delta is applied.
    """

    user: User
    account_id: int
    name: str
    bank: 'str | Bank'
    opened_on: date
    matures_on: date
    annual_rate: Decimal
    converted_on: date
    rate_kind: str
    forecast_terms: ForecastTerms = field(default_factory=ForecastTerms)
    withdrawal_terms: WithdrawalTerms = field(default_factory=WithdrawalTerms)
    top_up_terms: TopUpTerms = field(default_factory=TopUpTerms)


@dataclass(frozen=True)
class OpenExistingDepositCommand:
    """Command to record an already-active term deposit.

    Registers the deposit with its current balance and tracking start date
    through a neutral opening position — no monetary delta is applied,
    and no income or expense is created.
    """

    user: User
    name: str
    bank: 'str | Bank'
    currency: str
    current_balance: Decimal
    tracking_started_on: date
    opened_on: date
    matures_on: date
    annual_rate: Decimal
    rate_kind: str
    forecast_terms: ForecastTerms = field(default_factory=ForecastTerms)
    withdrawal_terms: WithdrawalTerms = field(default_factory=WithdrawalTerms)
    top_up_terms: TopUpTerms = field(default_factory=TopUpTerms)


@dataclass(frozen=True)
class AddFloatingRatePeriodCommand:
    """Command to append a new effective-rate period to a floating-rate term.

    The new period starts on starts_on and runs to the term's maturity date
    until superseded by a later period. The previous period's end date is
    trimmed to the day before starts_on — history is never rewritten.
    """

    user: User
    term_id: int
    starts_on: date
    annual_rate: Decimal
    note: str


@dataclass(frozen=True)
class RecalculateInterestForecastCommand:
    """Command to (re)build a term's expected interest payout forecast.

    Purely projective — never changes Account.balance, actual income or
    expense, or KPIs. Only forecast rows not yet marked confirmed are
    replaced; confirmed rows are left untouched.
    """

    user: User
    term_id: int


@dataclass(frozen=True)
class WithdrawDepositCommand:
    user: User
    deposit_id: int
    destination_account_id: int
    amount: Decimal
    effective_on: date
    exception_reason: str = ''


@dataclass(frozen=True)
class TopUpDepositCommand:
    user: User
    deposit_id: int
    source_account_id: int
    amount: Decimal
    effective_on: date
    exception_reason: str = ''


@dataclass(frozen=True)
class ConfirmInterestPaymentCommand:
    user: User
    deposit_id: int
    gross: Decimal
    withholding: Decimal
    net: Decimal
    posting_on: date
    value_on: date
    forecast_id: int | None = None
    reason: str = ''
    destination: str = DepositCapitalizationEvent.Destination.CAPITALIZATION
    destination_account_id: int | None = None


CapitalizeInterestCommand = ConfirmInterestPaymentCommand
