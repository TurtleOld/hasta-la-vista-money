"""Pure calculation core for deposit interest payout forecasting.

Purely computational — no ORM writes here. Given a term's contractual
terms and its rate periods, this module derives the accrual periods, the
day-count fractions, and the expected payout amounts. Never touches
Account.balance or any actual income/expense.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from django.utils.translation import gettext as _

from hasta_la_vista_money.deposits.models import DepositTerm

_ACCRUAL_PRECISION = Decimal('0.00000001')
_DEFAULT_MONEY_PRECISION = Decimal('0.01')
_DAYS_IN_YEAR = Decimal(365)
_WEEKEND_DAYS = frozenset({5, 6})
_MAX_ACCRUAL_YEARS = 100


class ProductionCalendar(Protocol):
    """A source of truth for which calendar dates are working days.

    is_complete tells callers whether this calendar accounts for every
    non-working day a real banking calendar would (e.g. public holidays),
    not only weekends. An incomplete calendar means a rolled date cannot be
    guaranteed accurate, and callers must mark it tentative.
    """

    is_complete: bool

    def is_working_day(self, day: date) -> bool: ...


class WeekendOnlyCalendar:
    """Treats Saturday and Sunday as non-working; ignores public holidays.

    is_complete is always False: this calendar does not know about
    Russian public holidays, so any date it rolls cannot be certified.
    """

    is_complete = False

    def is_working_day(self, day: date) -> bool:
        return day.weekday() not in _WEEKEND_DAYS


@dataclass(frozen=True)
class RateSegment:
    """A rate applicable to [starts_on, ends_on] within an accrual period."""

    starts_on: date
    ends_on: date
    annual_rate: Decimal | None


@dataclass(frozen=True)
class PrincipalChange:
    effective_on: date
    amount: Decimal


@dataclass(frozen=True)
class ForecastLine:
    """One projected interest payout, computed but not yet persisted."""

    payout_on: date
    amount: Decimal
    period_starts_on: date
    period_ends_on: date
    is_rate_undefined: bool
    is_date_tentative: bool


class EarlyClosureRecalculationScope(StrEnum):
    WHOLE_TERM = 'whole_term'
    CURRENT_PERIOD = 'current_period'
    WITHDRAWN_AMOUNT = 'withdrawn_amount'
    UNSUPPORTED = 'unsupported'


@dataclass(frozen=True)
class EarlyClosureForecast:
    scope: EarlyClosureRecalculationScope
    gross: Decimal | None
    is_uncertain: bool
    uncertainty_reason: str


def forecast_early_closure(
    *,
    scope: EarlyClosureRecalculationScope,
    closure_on: date,
    term_opened_on: date,
    current_period_opened_on: date,
    principal: Decimal,
    withdrawn_amount: Decimal,
    annual_rate: Decimal,
    day_count_convention: DepositTerm.DayCountConvention,
    accrual_start_included: bool,
    accrual_end_included: bool,
) -> EarlyClosureForecast:
    """Forecast a simple contractual early-closure recalculation."""
    if scope == EarlyClosureRecalculationScope.UNSUPPORTED:
        return EarlyClosureForecast(
            scope=scope,
            gross=None,
            is_uncertain=True,
            uncertainty_reason=_('Формула банка не поддерживается.'),
        )
    period_starts_on = (
        current_period_opened_on
        if scope == EarlyClosureRecalculationScope.CURRENT_PERIOD
        else term_opened_on
    )
    recalculated_principal = (
        withdrawn_amount
        if scope == EarlyClosureRecalculationScope.WITHDRAWN_AMOUNT
        else principal
    )
    amount, is_rate_undefined = compute_accrued_interest(
        period_starts_on,
        closure_on,
        start_included=accrual_start_included,
        end_included=accrual_end_included,
        day_count_convention=day_count_convention,
        principal=recalculated_principal,
        rate_segments=[
            RateSegment(period_starts_on, closure_on, annual_rate),
        ],
    )
    if is_rate_undefined:
        return EarlyClosureForecast(
            scope=scope,
            gross=None,
            is_uncertain=True,
            uncertainty_reason=_('Ставка пересчёта не определена.'),
        )
    return EarlyClosureForecast(
        scope=scope,
        gross=amount,
        is_uncertain=False,
        uncertainty_reason='',
    )


def year_length_for_day_count(
    day: date,
    convention: DepositTerm.DayCountConvention,
) -> Decimal:
    """Return the denominator (days in year) applicable to a given date.

    Args:
        day: The calendar date the fractional day falls on.
        convention: The term's day-count convention.

    Returns:
        365 for Actual/365, or 365/366 for Actual/Actual depending on
        whether `day`'s calendar year is a leap year.
    """
    if convention == DepositTerm.DayCountConvention.ACTUAL_365:
        return _DAYS_IN_YEAR
    year = day.year
    is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return Decimal(366) if is_leap else Decimal(365)


def accrual_days(
    period_starts_on: date,
    period_ends_on: date,
    *,
    start_included: bool,
    end_included: bool,
) -> list[date]:
    """Return the list of calendar days that accrue interest in a period.

    Args:
        period_starts_on: First calendar date of the accrual period.
        period_ends_on: Last calendar date of the accrual period.
        start_included: Whether period_starts_on itself accrues interest.
        end_included: Whether period_ends_on itself accrues interest.

    Returns:
        The list of accruing calendar dates, in order.
    """
    one_day = timedelta(days=1)
    first = period_starts_on if start_included else period_starts_on + one_day
    last = period_ends_on if end_included else period_ends_on - one_day
    if last < first:
        return []
    days = []
    current = first
    while current <= last:
        days.append(current)
        current += timedelta(days=1)
    return days


def rate_for_day(day: date, rate_segments: list[RateSegment]) -> Decimal | None:
    """Return the known annual rate covering `day`, or None if undefined.

    Raises:
        ValueError: If more than one segment covers `day` — rate segments
            for a term must be non-overlapping, so this signals a data
            invariant violation rather than a legitimately undefined rate.
    """
    covering = [
        segment
        for segment in rate_segments
        if segment.starts_on <= day <= segment.ends_on
    ]
    if len(covering) > 1:
        message = f'Multiple rate segments cover {day.isoformat()}'
        raise ValueError(message)
    if not covering:
        return None
    return covering[0].annual_rate


def compute_accrued_interest(
    period_starts_on: date,
    period_ends_on: date,
    *,
    start_included: bool,
    end_included: bool,
    day_count_convention: DepositTerm.DayCountConvention,
    principal: Decimal,
    rate_segments: list[RateSegment],
    principal_changes: list[PrincipalChange] | None = None,
) -> tuple[Decimal, bool]:
    """Compute high-precision accrued interest over an accrual period.

    Each accruing day contributes principal * (annual_rate / 100) /
    year_length(day) to a running total kept at full Decimal precision;
    the total is quantized to >= 8 decimal places only once, at the end.
    If any accruing day has no known rate, the period's rate is undefined
    and the accrued amount is not meaningful.

    Args:
        period_starts_on: First calendar date of the accrual period.
        period_ends_on: Last calendar date of the accrual period.
        start_included: Whether period_starts_on accrues interest.
        end_included: Whether period_ends_on accrues interest.
        day_count_convention: The term's day-count convention.
        principal: The deposit principal the rate applies to.
        rate_segments: Known rate segments covering (parts of) the period.

    Returns:
        A (accrued_amount, is_rate_undefined) pair. accrued_amount is zero
        when is_rate_undefined is True.
    """
    days = accrual_days(
        period_starts_on,
        period_ends_on,
        start_included=start_included,
        end_included=end_included,
    )
    total = Decimal(0)
    for day in days:
        rate = rate_for_day(day, rate_segments)
        if rate is None:
            return Decimal(0), True
        year_length = year_length_for_day_count(day, day_count_convention)
        daily_principal = principal
        if principal_changes is not None:
            daily_principal = sum(
                (
                    change.amount
                    for change in principal_changes
                    if change.effective_on <= day
                ),
                Decimal(),
            )
        total += daily_principal * rate / Decimal(100) / year_length
    return total.quantize(_ACCRUAL_PRECISION), False


def round_to_money(
    amount: Decimal,
    precision: Decimal = _DEFAULT_MONEY_PRECISION,
    rounding: str = 'ROUND_HALF_UP',
) -> Decimal:
    return amount.quantize(precision, rounding=rounding)


def roll_to_business_day(
    day: date,
    convention: DepositTerm.BusinessDayConvention,
    calendar: ProductionCalendar,
) -> tuple[date, bool]:
    """Apply a business-day roll convention to a payout date.

    Args:
        day: The unadjusted payout date.
        convention: The term's business-day roll convention.
        calendar: The working-day calendar to consult.

    Returns:
        A (rolled_date, is_tentative) pair. is_tentative is True whenever
        the date was actually moved and the calendar is not is_complete,
        since an incomplete calendar cannot guarantee the rolled date is
        truly a bank working day.
    """
    if (
        convention == DepositTerm.BusinessDayConvention.NONE
        or calendar.is_working_day(day)
    ):
        return day, False
    following = DepositTerm.BusinessDayConvention.FOLLOWING
    step = timedelta(days=1 if convention == following else -1)
    rolled = day
    while not calendar.is_working_day(rolled):
        rolled += step
    return rolled, not calendar.is_complete


def monthly_payout_dates(opened_on: date, matures_on: date) -> list[date]:
    """Return one payout date per calendar month, anchored to opened_on's day.

    The last generated date is always matures_on itself, regardless of the
    monthly anchor, so the final accrual period always closes on maturity.

    Raises:
        ValueError: If matures_on is not after opened_on, since a monthly
            schedule cannot be generated for a non-positive term length.
    """
    if matures_on <= opened_on:
        message = 'matures_on must be after opened_on'
        raise ValueError(message)
    dates: list[date] = []
    year, month = opened_on.year, opened_on.month
    day_of_month = opened_on.day
    latest_year = opened_on.year + _MAX_ACCRUAL_YEARS
    while True:
        month += 1
        if month > _MONTHS_IN_YEAR:
            month = 1
            year += 1
        if year > latest_year:
            message = 'monthly_payout_dates exceeded the maximum term length'
            raise ValueError(message)
        candidate = _clamp_to_month(year, month, day_of_month)
        if candidate >= matures_on:
            break
        dates.append(candidate)
    dates.append(matures_on)
    return dates


_MONTHS_IN_YEAR = 12


def _clamp_to_month(year: int, month: int, day: int) -> date:
    if month == _MONTHS_IN_YEAR:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day_of_month = (next_month_first - timedelta(days=1)).day
    return date(year, month, min(day, last_day_of_month))


def build_forecast(
    *,
    opened_on: date,
    matures_on: date,
    principal: Decimal,
    rate_segments: list[RateSegment],
    day_count_convention: DepositTerm.DayCountConvention,
    accrual_start_included: bool,
    accrual_end_included: bool,
    payout_schedule_kind: DepositTerm.PayoutScheduleKind,
    custom_payout_dates: list[date],
    business_day_convention: DepositTerm.BusinessDayConvention,
    calendar: ProductionCalendar,
    principal_changes: list[PrincipalChange] | None = None,
    money_precision: Decimal = _DEFAULT_MONEY_PRECISION,
    rounding_rule: str = 'ROUND_HALF_UP',
    accrual_starts_on: date | None = None,
) -> list[ForecastLine]:
    """Compute the full expected-payout schedule for a deposit term.

    Splits the term into accrual periods according to the payout schedule
    kind, computes accrued interest for each, and applies the business-day
    roll convention to each payout date. Purely computational: does not
    read or write any persisted state.

    Args:
        opened_on: Term's opening date (start of the first accrual period).
        matures_on: Term's maturity date (end of the last accrual period).
        principal: The deposit principal the rate applies to.
        rate_segments: The term's known rate periods.
        day_count_convention: The term's day-count convention.
        accrual_start_included: Whether an accrual period's first day
            accrues interest.
        accrual_end_included: Whether an accrual period's last day accrues
            interest.
        payout_schedule_kind: The term's payout schedule kind.
        custom_payout_dates: User-defined payout dates, used only when
            payout_schedule_kind is CUSTOM. Sorted ascending regardless of
            input order; matures_on is appended automatically if absent,
            since interest through maturity must always be projected.
        business_day_convention: The term's business-day roll convention.
        calendar: The working-day calendar consulted for rolls.
        money_precision: Smallest currency unit for rounding final amounts.
        rounding_rule: Decimal rounding strategy (e.g. 'ROUND_HALF_UP').
        accrual_starts_on: Date from which interest starts accruing.
            Defaults to opened_on when None.

    Returns:
        One ForecastLine per accrual period, in chronological order.
    """
    if accrual_starts_on is None:
        accrual_starts_on = opened_on
    if payout_schedule_kind == DepositTerm.PayoutScheduleKind.MONTHLY:
        unadjusted_payout_dates = monthly_payout_dates(
            accrual_starts_on,
            matures_on,
        )
    elif payout_schedule_kind == DepositTerm.PayoutScheduleKind.CUSTOM:
        unadjusted_payout_dates = sorted(custom_payout_dates)
        if not unadjusted_payout_dates or unadjusted_payout_dates[-1] != (
            matures_on
        ):
            unadjusted_payout_dates.append(matures_on)
    else:
        unadjusted_payout_dates = [matures_on]

    lines = []
    period_start = accrual_starts_on
    for unadjusted_payout_on in unadjusted_payout_dates:
        period_end = unadjusted_payout_on
        amount, is_rate_undefined = compute_accrued_interest(
            period_start,
            period_end,
            start_included=accrual_start_included,
            end_included=accrual_end_included,
            day_count_convention=day_count_convention,
            principal=principal,
            rate_segments=rate_segments,
            principal_changes=principal_changes,
        )
        payout_on, is_date_tentative = roll_to_business_day(
            unadjusted_payout_on,
            business_day_convention,
            calendar,
        )
        lines.append(
            ForecastLine(
                payout_on=payout_on,
                amount=Decimal(0)
                if is_rate_undefined
                else round_to_money(
                    amount,
                    precision=money_precision,
                    rounding=rounding_rule,
                ),
                period_starts_on=period_start,
                period_ends_on=period_end,
                is_rate_undefined=is_rate_undefined,
                is_date_tentative=is_date_tentative,
            ),
        )
        period_start = period_end + timedelta(days=1)
    return lines
