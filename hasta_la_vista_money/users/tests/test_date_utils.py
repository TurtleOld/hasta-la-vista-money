"""Tests for date utilities.

This module provides test cases for date utility functions including
month calculations, period dates, and decimal conversions.
"""

from datetime import UTC, date, datetime
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from hasta_la_vista_money.users.utils.date_utils import (
    get_last_month_start_end,
    get_month_start_end,
    get_period_dates,
    to_decimal,
)


class DateUtilsTest(TestCase):
    """Test cases for date utilities.

    Tests month start/end calculations, period dates, and conversions.
    """

    def test_get_month_start_end(self) -> None:
        """Test getting month start and end dates."""
        test_date = date(2024, 3, 15)
        month_start, month_end = get_month_start_end(test_date)

        self.assertEqual(month_start, date(2024, 3, 1))
        self.assertEqual(month_end, date(2024, 3, 31))

    def test_get_month_start_end_none(self) -> None:
        """Test getting month start and end with None input."""
        month_start, _ = get_month_start_end(None)

        today = timezone.localdate()
        expected_start = today.replace(day=1)
        self.assertEqual(month_start, expected_start)

    def test_get_last_month_start_end(self) -> None:
        """Test getting last month start and end dates."""
        test_date = date(2024, 3, 15)
        last_month_start, last_month_end = get_last_month_start_end(test_date)

        self.assertEqual(last_month_start, date(2024, 2, 1))
        self.assertEqual(last_month_end, date(2024, 2, 29))

    def test_get_period_dates_month(self) -> None:
        """Test getting period dates for month."""
        test_date = date(2024, 3, 15)
        period_dates = get_period_dates('month', test_date)

        self.assertIn('current_start', period_dates)
        self.assertIn('current_end', period_dates)
        self.assertIn('previous_start', period_dates)
        self.assertIn('previous_end', period_dates)

        self.assertIsInstance(period_dates['current_start'], datetime)
        self.assertIsInstance(period_dates['current_end'], datetime)

    @override_settings(TIME_ZONE='Europe/Moscow')
    def test_get_period_dates_uses_local_date(self) -> None:
        """Test that current period ends on the local, not UTC, date."""
        utc_now = datetime(2026, 9, 26, 21, 30, tzinfo=UTC)
        with patch('django.utils.timezone.now', return_value=utc_now):
            period_dates = get_period_dates('month')

        self.assertEqual(
            timezone.localtime(period_dates['current_end']).date(),
            date(2026, 9, 27),
        )

    def test_to_decimal(self) -> None:
        """Test conversion to Decimal."""
        self.assertEqual(to_decimal(10), 10)
        self.assertEqual(to_decimal('10.5'), 10.5)
        self.assertEqual(to_decimal(None), 0)
        self.assertEqual(to_decimal(10.5), 10.5)
