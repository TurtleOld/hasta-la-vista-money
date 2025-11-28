"""Тесты для сервисов аналитики дашборда."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.income.models import IncomeCategory
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
    """Тесты для функции calculate_linear_trend."""

    def test_calculate_linear_trend_with_sufficient_data(self) -> None:
        """Тест расчёта тренда с достаточным количеством данных."""
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
        """Тест расчёта тренда с недостаточным количеством данных."""
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
        """Тест расчёта тренда с пустыми данными."""
        dates: list[date] = []
        values: list[Decimal] = []

        result = calculate_linear_trend(dates, values)

        self.assertIn('error', result)

    def test_calculate_linear_trend_forecast_dates(self) -> None:
        """Тест, что прогноз содержит правильные даты."""
        today = timezone.now().date()
        dates = [today - timedelta(days=30 * i) for i in range(5, -1, -1)]
        values = [Decimal(1000) * (i + 1) for i in range(6)]

        result = calculate_linear_trend(dates, values)

        self.assertEqual(len(result['forecast']), 30)
        for forecast_item in result['forecast']:
            self.assertIn('date', forecast_item)
            self.assertIn('value', forecast_item)


class GetPeriodComparisonTest(TestCase):
    """Тесты для функции get_period_comparison."""

    fixtures: Sequence[str] = [
        'users.yaml',
        'finance_account.yaml',
        'expense_cat.yaml',
        'expense.yaml',
        'income_cat.yaml',
        'income.yaml',
    ]

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: UserType = user

    def test_get_period_comparison_month(self) -> None:
        """Тест сравнения периодов для месяца."""
        result = get_period_comparison(self.user, 'month')

        self.assertIn('current', result)
        self.assertIn('previous', result)
        self.assertIn('expenses', result['current'])
        self.assertIn('income', result['current'])
        self.assertIn('expenses', result['previous'])
        self.assertIn('income', result['previous'])

    def test_get_period_comparison_quarter(self) -> None:
        """Тест сравнения периодов для квартала."""
        result = get_period_comparison(self.user, 'quarter')

        self.assertIn('current', result)
        self.assertIn('previous', result)

    def test_get_period_comparison_year(self) -> None:
        """Тест сравнения периодов для года."""
        result = get_period_comparison(self.user, 'year')

        self.assertIn('current', result)
        self.assertIn('previous', result)


class GetDrillDownDataTest(TestCase):
    """Тесты для функции get_drill_down_data."""

    fixtures: Sequence[str] = [
        'users.yaml',
        'finance_account.yaml',
        'expense_cat.yaml',
        'expense.yaml',
        'income_cat.yaml',
        'income.yaml',
    ]

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: UserType = user

    def test_get_drill_down_data_expense(self) -> None:
        """Тест получения drill-down данных для расходов."""
        category = ExpenseCategory.objects.filter(user=self.user).first()
        if category is None:
            self.skipTest('No expense category found in fixtures')

        result = get_drill_down_data(self.user, str(category.pk), 'expense')

        self.assertIn('data', result)
        self.assertIsInstance(result['data'], list)

    def test_get_drill_down_data_income(self) -> None:
        """Тест получения drill-down данных для доходов."""
        category = IncomeCategory.objects.filter(user=self.user).first()
        if category is None:
            self.skipTest('No income category found in fixtures')

        result = get_drill_down_data(self.user, str(category.pk), 'income')

        self.assertIn('data', result)
        self.assertIsInstance(result['data'], list)

    def test_get_drill_down_data_invalid_category(self) -> None:
        """Тест с несуществующей категорией."""
        invalid_category_id = 99999

        result = get_drill_down_data(
            self.user,
            str(invalid_category_id),
            'expense',
        )

        self.assertIn('data', result)
        self.assertEqual(result['data'], [])
