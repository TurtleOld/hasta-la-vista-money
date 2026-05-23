"""Tests for dashboard analytics services."""

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Category, TransactionType
from hasta_la_vista_money.users.services.dashboard_analytics import (
    calculate_linear_trend,
    get_drill_down_data,
    get_period_comparison,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class CalculateLinearTrendTest(TestCase):
    """Test cases for calculate_linear_trend function."""

    def test_calculate_linear_trend_with_sufficient_data(self) -> None:
        today = timezone.now().date()
        dates = [today - timedelta(days=30 * i) for i in range(5, -1, -1)]
        values = [
            Decimal(1000),
            Decimal(1200),
            Decimal(1100),
            Decimal(1300),
            Decimal(1250),
            Decimal(1400),
        ]

        result = calculate_linear_trend(dates, values)

        self.assertIn('slope', result)
        self.assertIn('intercept', result)
        self.assertIn('r_squared', result)
        self.assertIn('trend_line', result)
        self.assertIn('forecast', result)
        self.assertIsInstance(result['slope'], float)
        self.assertIsInstance(result['intercept'], float)
        self.assertIsInstance(result['r_squared'], float)
        self.assertIsInstance(result['trend_line'], list)
        self.assertIsInstance(result['forecast'], list)
        self.assertEqual(len(result['forecast']), 30)

    def test_calculate_linear_trend_with_insufficient_data(self) -> None:
        dates = [timezone.now().date()]
        values = [Decimal(1000)]

        result = calculate_linear_trend(dates, values)

        self.assertIn('error', result)
        self.assertEqual(result['slope'], 0.0)
        self.assertEqual(result['intercept'], 0.0)
        self.assertEqual(result['r_squared'], 0.0)
        self.assertEqual(result['trend_line'], [])
        self.assertEqual(result['forecast'], [])

    def test_calculate_linear_trend_with_empty_data(self) -> None:
        dates: list[date] = []
        values: list[Decimal] = []

        result = calculate_linear_trend(dates, values)

        self.assertIn('error', result)

    def test_calculate_linear_trend_forecast_dates(self) -> None:
        today = timezone.now().date()
        dates = [today - timedelta(days=30 * i) for i in range(5, -1, -1)]
        values = [Decimal(1000) * (i + 1) for i in range(6)]

        result = calculate_linear_trend(dates, values)

        self.assertEqual(len(result['forecast']), 30)
        for forecast_item in result['forecast']:
            self.assertIn('date', forecast_item)
            self.assertIn('value', forecast_item)


class GetPeriodComparisonTest(TestCase):
    """Test cases for get_period_comparison function."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='analytics-user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Main',
            balance=Decimal('1000.00'),
        )
        cache.clear()

    def test_get_period_comparison_month(self) -> None:
        result = get_period_comparison(self.user, 'month')

        self.assertIn('current', result)
        self.assertIn('previous', result)
        self.assertIn('expenses', result['current'])
        self.assertIn('income', result['current'])
        self.assertIn('expenses', result['previous'])
        self.assertIn('income', result['previous'])

    def test_get_period_comparison_quarter(self) -> None:
        result = get_period_comparison(self.user, 'quarter')

        self.assertIn('current', result)
        self.assertIn('previous', result)

    def test_get_period_comparison_year(self) -> None:
        result = get_period_comparison(self.user, 'year')

        self.assertIn('current', result)
        self.assertIn('previous', result)

    def test_get_period_comparison_uses_two_aggregate_queries(self) -> None:
        with CaptureQueriesContext(connection) as queries:
            result = get_period_comparison(self.user, 'month')

        self.assertIn('current', result)
        self.assertLessEqual(len(queries), 2)

    def test_get_period_comparison_uses_cache(self) -> None:
        get_period_comparison(self.user, 'quarter')

        with CaptureQueriesContext(connection) as queries:
            cached_result = get_period_comparison(self.user, 'quarter')

        self.assertIn('current', cached_result)
        self.assertEqual(len(queries), 0)


class GetDrillDownDataTest(TestCase):
    """Test cases for get_drill_down_data function."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='drill-down-user',
            password='pass',  # nosec B106: test-only password
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Groceries',
            type=TransactionType.EXPENSE,
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Salary',
            type=TransactionType.INCOME,
        )

    def test_get_drill_down_data_expense(self) -> None:
        result = get_drill_down_data(
            self.user,
            str(self.expense_category.pk),
            date_str=None,
            data_type='expense',
        )

        self.assertIn('data', result)
        self.assertIsInstance(result['data'], list)

    def test_get_drill_down_data_income(self) -> None:
        result = get_drill_down_data(
            self.user,
            str(self.income_category.pk),
            date_str=None,
            data_type='income',
        )

        self.assertIn('data', result)
        self.assertIsInstance(result['data'], list)

    def test_get_drill_down_data_invalid_category(self) -> None:
        invalid_category_id = 99999

        result = get_drill_down_data(
            self.user,
            str(invalid_category_id),
            date_str=None,
            data_type='expense',
        )

        self.assertIn('data', result)
        self.assertEqual(result['data'], [])
