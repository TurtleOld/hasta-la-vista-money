from datetime import date
from decimal import Decimal
from typing import NamedTuple

from django.test import SimpleTestCase

from hasta_la_vista_money.deposits.interest_forecast import (
    EarlyClosureForecast,
    EarlyClosureRecalculationScope,
    RateSegment,
    WeekendOnlyCalendar,
    accrual_days,
    build_forecast,
    compute_accrued_interest,
    forecast_early_closure,
    monthly_payout_dates,
    rate_for_day,
    roll_to_business_day,
    round_to_money,
    year_length_for_day_count,
)
from hasta_la_vista_money.deposits.models import DepositTerm

_ACTUAL_365 = DepositTerm.DayCountConvention.ACTUAL_365
_ACTUAL_ACTUAL = DepositTerm.DayCountConvention.ACTUAL_ACTUAL


class EarlyClosureForecastTests(SimpleTestCase):
    class Case(NamedTuple):
        scope: EarlyClosureRecalculationScope
        expected_gross: Decimal

    CASES = (
        Case(
            EarlyClosureRecalculationScope.WHOLE_TERM,
            Decimal('495.89041096'),
        ),
        Case(
            EarlyClosureRecalculationScope.CURRENT_PERIOD,
            Decimal('167.12328767'),
        ),
        Case(
            EarlyClosureRecalculationScope.WITHDRAWN_AMOUNT,
            Decimal('123.97260274'),
        ),
    )

    def test_supported_scopes_recalculate_at_early_closure_rate(self) -> None:
        for case in self.CASES:
            with self.subTest(scope=case.scope):
                forecast = forecast_early_closure(
                    scope=case.scope,
                    closure_on=date(2026, 7, 1),
                    term_opened_on=date(2026, 1, 1),
                    current_period_opened_on=date(2026, 5, 1),
                    principal=Decimal('100000.00'),
                    withdrawn_amount=Decimal('25000.00'),
                    annual_rate=Decimal('1.00'),
                    day_count_convention=_ACTUAL_365,
                    accrual_start_included=True,
                    accrual_end_included=False,
                )

                self.assertEqual(
                    forecast,
                    EarlyClosureForecast(
                        scope=case.scope,
                        gross=case.expected_gross,
                        is_uncertain=False,
                        uncertainty_reason='',
                    ),
                )

    def test_unsupported_bank_formula_returns_no_amount(self) -> None:
        forecast = forecast_early_closure(
            scope=EarlyClosureRecalculationScope.UNSUPPORTED,
            closure_on=date(2026, 7, 1),
            term_opened_on=date(2026, 1, 1),
            current_period_opened_on=date(2026, 5, 1),
            principal=Decimal('100000.00'),
            withdrawn_amount=Decimal('100000.00'),
            annual_rate=Decimal('1.00'),
            day_count_convention=_ACTUAL_365,
            accrual_start_included=True,
            accrual_end_included=False,
        )

        self.assertIsNone(forecast.gross)
        self.assertTrue(forecast.is_uncertain)
        self.assertEqual(
            forecast.uncertainty_reason,
            'Формула банка не поддерживается.',
        )


class YearLengthTests(SimpleTestCase):
    class Case(NamedTuple):
        day: date
        convention: DepositTerm.DayCountConvention
        expected: Decimal

    CASES = (
        Case(date(2024, 3, 1), _ACTUAL_365, Decimal(365)),
        Case(date(2024, 3, 1), _ACTUAL_ACTUAL, Decimal(366)),
        Case(date(2023, 3, 1), _ACTUAL_ACTUAL, Decimal(365)),
        Case(date(2000, 3, 1), _ACTUAL_ACTUAL, Decimal(366)),
        Case(date(1900, 3, 1), _ACTUAL_ACTUAL, Decimal(365)),
    )

    def test_year_length_matches_expected_table(self) -> None:
        for case in self.CASES:
            with self.subTest(case=case):
                self.assertEqual(
                    year_length_for_day_count(case.day, case.convention),
                    case.expected,
                )


class AccrualDaysTests(SimpleTestCase):
    def test_include_start_exclude_end_by_default_convention(self) -> None:
        days = accrual_days(
            date(2026, 1, 1),
            date(2026, 1, 5),
            start_included=True,
            end_included=False,
        )
        self.assertEqual(
            days,
            [
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 1, 3),
                date(2026, 1, 4),
            ],
        )

    def test_include_both_start_and_end(self) -> None:
        days = accrual_days(
            date(2026, 1, 1),
            date(2026, 1, 3),
            start_included=True,
            end_included=True,
        )
        self.assertEqual(
            days,
            [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)],
        )

    def test_exclude_both_start_and_end(self) -> None:
        days = accrual_days(
            date(2026, 1, 1),
            date(2026, 1, 3),
            start_included=False,
            end_included=False,
        )
        self.assertEqual(days, [date(2026, 1, 2)])

    def test_single_day_period_excluding_both_ends_is_empty(self) -> None:
        days = accrual_days(
            date(2026, 1, 1),
            date(2026, 1, 1),
            start_included=False,
            end_included=False,
        )
        self.assertEqual(days, [])


class RateForDayTests(SimpleTestCase):
    def test_returns_none_when_no_segment_covers_the_day(self) -> None:
        segments = [
            RateSegment(date(2026, 1, 1), date(2026, 1, 10), Decimal(10)),
        ]
        self.assertIsNone(rate_for_day(date(2026, 1, 20), segments))

    def test_returns_rate_of_covering_segment(self) -> None:
        segments = [
            RateSegment(date(2026, 1, 1), date(2026, 1, 10), Decimal(10)),
            RateSegment(date(2026, 1, 11), date(2026, 1, 20), Decimal(12)),
        ]
        self.assertEqual(
            rate_for_day(date(2026, 1, 15), segments),
            Decimal(12),
        )

    def test_overlapping_segments_raise_instead_of_picking_one(self) -> None:
        """Rate segments for a term must be non-overlapping; a day covered
        by more than one segment is a data invariant violation, not a
        legitimately ambiguous rate."""
        segments = [
            RateSegment(date(2026, 1, 1), date(2026, 1, 15), Decimal(10)),
            RateSegment(date(2026, 1, 10), date(2026, 1, 20), Decimal(12)),
        ]
        with self.assertRaises(ValueError):
            rate_for_day(date(2026, 1, 12), segments)


class ComputeAccruedInterestTests(SimpleTestCase):
    def test_fixed_rate_actual_365_matches_manual_calculation(self) -> None:
        segments = [
            RateSegment(date(2026, 1, 1), date(2026, 12, 31), Decimal(12)),
        ]
        amount, is_undefined = compute_accrued_interest(
            date(2026, 1, 1),
            date(2026, 1, 31),
            start_included=True,
            end_included=False,
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_365,
            principal=Decimal(100000),
            rate_segments=segments,
        )
        self.assertFalse(is_undefined)
        expected_daily = (
            Decimal(100000) * Decimal(12) / Decimal(100) / Decimal(365)
        ).quantize(Decimal('0.00000001'))
        expected_total = round_to_money(expected_daily * 30)
        self.assertEqual(round_to_money(amount), expected_total)

    def test_rate_change_mid_period_uses_both_segments(self) -> None:
        segments = [
            RateSegment(date(2026, 1, 1), date(2026, 1, 15), Decimal(10)),
            RateSegment(date(2026, 1, 16), date(2026, 1, 31), Decimal(20)),
        ]
        amount, is_undefined = compute_accrued_interest(
            date(2026, 1, 1),
            date(2026, 1, 31),
            start_included=True,
            end_included=True,
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_365,
            principal=Decimal(100000),
            rate_segments=segments,
        )
        self.assertFalse(is_undefined)
        low_days = 15
        high_days = 16
        daily_low = (
            Decimal(100000) * Decimal(10) / Decimal(100) / Decimal(365)
        ).quantize(Decimal('0.00000001'))
        daily_high = (
            Decimal(100000) * Decimal(20) / Decimal(100) / Decimal(365)
        ).quantize(Decimal('0.00000001'))
        expected = round_to_money(
            daily_low * low_days + daily_high * high_days,
        )
        self.assertEqual(round_to_money(amount), expected)

    def test_undefined_future_floating_rate_is_reported_not_silently_extended(
        self,
    ) -> None:
        segments = [
            RateSegment(date(2026, 1, 1), date(2026, 1, 15), Decimal(10)),
        ]
        amount, is_undefined = compute_accrued_interest(
            date(2026, 1, 1),
            date(2026, 1, 31),
            start_included=True,
            end_included=False,
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_365,
            principal=Decimal(100000),
            rate_segments=segments,
        )
        self.assertTrue(is_undefined)
        self.assertEqual(amount, Decimal(0))

    def test_leap_year_actual_actual_uses_366_denominator(self) -> None:
        segments = [
            RateSegment(date(2024, 1, 1), date(2024, 12, 31), Decimal(12)),
        ]
        amount, is_undefined = compute_accrued_interest(
            date(2024, 1, 1),
            date(2024, 1, 2),
            start_included=True,
            end_included=True,
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_ACTUAL,
            principal=Decimal(100000),
            rate_segments=segments,
        )
        self.assertFalse(is_undefined)
        daily = (
            Decimal(100000) * Decimal(12) / Decimal(100) / Decimal(366)
        ).quantize(Decimal('0.00000001'))
        self.assertEqual(round_to_money(amount), round_to_money(daily * 2))


class RoundToMoneyTests(SimpleTestCase):
    class Case(NamedTuple):
        raw: Decimal
        expected: Decimal

    CASES = (
        Case(Decimal('1.005'), Decimal('1.01')),
        Case(Decimal('1.004'), Decimal('1.00')),
        Case(Decimal('0.00000001'), Decimal('0.00')),
        Case(Decimal('1000000.005'), Decimal('1000000.01')),
    )

    def test_half_up_money_rounding(self) -> None:
        for case in self.CASES:
            with self.subTest(case=case):
                self.assertEqual(round_to_money(case.raw), case.expected)


class RollToBusinessDayTests(SimpleTestCase):
    def test_no_roll_convention_never_moves_the_date(self) -> None:
        saturday = date(2026, 1, 3)
        rolled, is_tentative = roll_to_business_day(
            saturday,
            DepositTerm.BusinessDayConvention.NONE,
            WeekendOnlyCalendar(),
        )
        self.assertEqual(rolled, saturday)
        self.assertFalse(is_tentative)

    def test_already_working_day_is_never_marked_tentative(self) -> None:
        monday = date(2026, 1, 5)
        rolled, is_tentative = roll_to_business_day(
            monday,
            DepositTerm.BusinessDayConvention.FOLLOWING,
            WeekendOnlyCalendar(),
        )
        self.assertEqual(rolled, monday)
        self.assertFalse(is_tentative)

    def test_following_rolls_saturday_forward_to_monday(self) -> None:
        saturday = date(2026, 1, 3)
        rolled, is_tentative = roll_to_business_day(
            saturday,
            DepositTerm.BusinessDayConvention.FOLLOWING,
            WeekendOnlyCalendar(),
        )
        self.assertEqual(rolled, date(2026, 1, 5))
        self.assertTrue(is_tentative)

    def test_preceding_rolls_sunday_backward_to_friday(self) -> None:
        sunday = date(2026, 1, 4)
        rolled, is_tentative = roll_to_business_day(
            sunday,
            DepositTerm.BusinessDayConvention.PRECEDING,
            WeekendOnlyCalendar(),
        )
        self.assertEqual(rolled, date(2026, 1, 2))
        self.assertTrue(is_tentative)

    def test_incomplete_calendar_marks_rolled_date_tentative(self) -> None:
        calendar = WeekendOnlyCalendar()
        self.assertFalse(calendar.is_complete)
        _, is_tentative = roll_to_business_day(
            date(2026, 1, 3),
            DepositTerm.BusinessDayConvention.FOLLOWING,
            calendar,
        )
        self.assertTrue(is_tentative)


class MonthlyPayoutDatesTests(SimpleTestCase):
    def test_generates_one_date_per_month_ending_on_maturity(self) -> None:
        dates = monthly_payout_dates(date(2026, 1, 15), date(2026, 4, 15))
        self.assertEqual(
            dates,
            [date(2026, 2, 15), date(2026, 3, 15), date(2026, 4, 15)],
        )

    def test_clamps_to_shorter_months(self) -> None:
        dates = monthly_payout_dates(date(2026, 1, 31), date(2026, 4, 30))
        self.assertEqual(
            dates,
            [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)],
        )

    def test_last_date_is_always_maturity_even_off_anchor(self) -> None:
        dates = monthly_payout_dates(date(2026, 1, 20), date(2026, 2, 10))
        self.assertEqual(dates, [date(2026, 2, 10)])

    def test_matures_on_not_after_opened_on_raises(self) -> None:
        """A backwards or zero-length term must raise immediately instead
        of looping without termination."""
        with self.assertRaises(ValueError):
            monthly_payout_dates(date(2026, 2, 10), date(2026, 1, 20))
        with self.assertRaises(ValueError):
            monthly_payout_dates(date(2026, 2, 10), date(2026, 2, 10))


class BuildForecastTests(SimpleTestCase):
    def test_maturity_schedule_produces_single_line(self) -> None:
        lines = build_forecast(
            opened_on=date(2026, 1, 1),
            matures_on=date(2026, 12, 31),
            principal=Decimal(100000),
            rate_segments=[
                RateSegment(date(2026, 1, 1), date(2026, 12, 31), Decimal(12)),
            ],
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_365,
            accrual_start_included=True,
            accrual_end_included=False,
            payout_schedule_kind=DepositTerm.PayoutScheduleKind.MATURITY,
            custom_payout_dates=[],
            business_day_convention=DepositTerm.BusinessDayConvention.NONE,
            calendar=WeekendOnlyCalendar(),
        )
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line.payout_on, date(2026, 12, 31))
        self.assertEqual(line.period_starts_on, date(2026, 1, 1))
        self.assertEqual(line.period_ends_on, date(2026, 12, 31))
        self.assertFalse(line.is_rate_undefined)
        self.assertGreater(line.amount, Decimal(0))

    def test_monthly_schedule_produces_one_line_per_month(self) -> None:
        lines = build_forecast(
            opened_on=date(2026, 1, 15),
            matures_on=date(2026, 4, 15),
            principal=Decimal(100000),
            rate_segments=[
                RateSegment(date(2026, 1, 15), date(2026, 4, 15), Decimal(10)),
            ],
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_365,
            accrual_start_included=True,
            accrual_end_included=False,
            payout_schedule_kind=DepositTerm.PayoutScheduleKind.MONTHLY,
            custom_payout_dates=[],
            business_day_convention=DepositTerm.BusinessDayConvention.NONE,
            calendar=WeekendOnlyCalendar(),
        )
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[-1].payout_on, date(2026, 4, 15))

    def test_custom_schedule_uses_supplied_dates(self) -> None:
        custom_dates = [date(2026, 2, 1), date(2026, 3, 15)]
        lines = build_forecast(
            opened_on=date(2026, 1, 1),
            matures_on=date(2026, 3, 15),
            principal=Decimal(50000),
            rate_segments=[
                RateSegment(date(2026, 1, 1), date(2026, 3, 15), Decimal(8)),
            ],
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_365,
            accrual_start_included=True,
            accrual_end_included=False,
            payout_schedule_kind=DepositTerm.PayoutScheduleKind.CUSTOM,
            custom_payout_dates=custom_dates,
            business_day_convention=DepositTerm.BusinessDayConvention.NONE,
            calendar=WeekendOnlyCalendar(),
        )
        self.assertEqual([line.payout_on for line in lines], custom_dates)

    def test_custom_schedule_appends_maturity_when_missing(self) -> None:
        """Interest through maturity must always be projected, even if the
        user's custom schedule didn't explicitly include that date."""
        lines = build_forecast(
            opened_on=date(2026, 1, 1),
            matures_on=date(2026, 3, 15),
            principal=Decimal(50000),
            rate_segments=[
                RateSegment(date(2026, 1, 1), date(2026, 3, 15), Decimal(8)),
            ],
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_365,
            accrual_start_included=True,
            accrual_end_included=False,
            payout_schedule_kind=DepositTerm.PayoutScheduleKind.CUSTOM,
            custom_payout_dates=[date(2026, 2, 1)],
            business_day_convention=DepositTerm.BusinessDayConvention.NONE,
            calendar=WeekendOnlyCalendar(),
        )
        self.assertEqual(
            [line.payout_on for line in lines],
            [date(2026, 2, 1), date(2026, 3, 15)],
        )

    def test_undefined_floating_period_is_flagged_and_zero(self) -> None:
        lines = build_forecast(
            opened_on=date(2026, 1, 1),
            matures_on=date(2026, 3, 1),
            principal=Decimal(100000),
            rate_segments=[
                RateSegment(date(2026, 1, 1), date(2026, 1, 31), Decimal(10)),
            ],
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_365,
            accrual_start_included=True,
            accrual_end_included=False,
            payout_schedule_kind=DepositTerm.PayoutScheduleKind.MATURITY,
            custom_payout_dates=[],
            business_day_convention=DepositTerm.BusinessDayConvention.NONE,
            calendar=WeekendOnlyCalendar(),
        )
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].is_rate_undefined)
        self.assertEqual(lines[0].amount, Decimal(0))

    def test_business_day_roll_marks_line_tentative(self) -> None:
        lines = build_forecast(
            opened_on=date(2026, 1, 1),
            matures_on=date(2026, 1, 3),
            principal=Decimal(100000),
            rate_segments=[
                RateSegment(date(2026, 1, 1), date(2026, 1, 3), Decimal(10)),
            ],
            day_count_convention=DepositTerm.DayCountConvention.ACTUAL_365,
            accrual_start_included=True,
            accrual_end_included=True,
            payout_schedule_kind=DepositTerm.PayoutScheduleKind.MATURITY,
            custom_payout_dates=[],
            business_day_convention=DepositTerm.BusinessDayConvention.FOLLOWING,
            calendar=WeekendOnlyCalendar(),
        )
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].payout_on, date(2026, 1, 5))
        self.assertTrue(lines[0].is_date_tentative)
