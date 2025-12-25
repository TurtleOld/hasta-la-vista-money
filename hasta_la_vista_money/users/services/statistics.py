"""Service for user statistics.

This module provides service for calculating and retrieving user statistics,
including account balances, expenses, income, and categories.
"""

from datetime import datetime, time
from decimal import Decimal

import structlog
from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone
from typing_extensions import TypedDict

from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.utils.date_utils import (
    get_last_month_start_end,
    get_month_start_end,
    to_decimal,
)

logger = structlog.get_logger(__name__)


class UserStatistics(TypedDict, total=False):
    """User statistics data structure.

    Attributes:
        total_balance: Total balance of all user accounts.
        accounts_count: Number of user accounts.
        current_month_expenses: Total expenses for current month.
        current_month_income: Total income for current month.
        last_month_expenses: Total expenses for last month.
        last_month_income: Total income for last month.
        recent_expenses: List of recent expense transactions.
        recent_incomes: List of recent income transactions.
        receipts_count: Number of user receipts.
        top_expense_categories: Top expense categories for current month.
        monthly_savings: Savings for current month (income - expenses).
        last_month_savings: Savings for last month.
    """

    total_balance: Decimal
    accounts_count: int
    current_month_expenses: Decimal
    current_month_income: Decimal
    last_month_expenses: Decimal
    last_month_income: Decimal
    recent_expenses: list[Expense]
    recent_incomes: list[Income]
    receipts_count: int
    top_expense_categories: list[dict[str, str | Decimal]]
    monthly_savings: Decimal
    last_month_savings: Decimal


class UserStatisticsService:
    """Service for user statistics.

    Provides methods for calculating various user statistics metrics
    using repositories and caching for optimization.
    """

    def __init__(
        self,
        statistics_repository: StatisticsRepository,
    ) -> None:
        """Initialize UserStatisticsService.

        Args:
            statistics_repository: Repository for statistics data access.
        """
        self.statistics_repository = statistics_repository
        self.cache_timeout = 300

    def get_user_statistics(self, user: User) -> UserStatistics:
        """Get complete user statistics.

        Retrieves user statistics including account balances, expenses and
        income for current and last month, recent transactions, and top
        categories. Uses caching for optimization.

        Args:
            user: User to get statistics for.

        Returns:
            UserStatistics: Dictionary with user statistics.

        Raises:
            ValueError: If user is invalid.
            DatabaseError: On database errors.
        """
        if not user or not hasattr(user, 'id'):
            error_msg = 'Invalid user provided to get_user_statistics'
            logger.error(error_msg, user_id=getattr(user, 'id', None))
            raise ValueError(error_msg)

        try:
            cache_key = self._get_cache_key(user)
            cached_statistics = cache.get(cache_key)

            if cached_statistics is not None:
                logger.debug(
                    'Statistics retrieved from cache',
                    user_id=user.id,
                    cache_key=cache_key,
                )
                return cached_statistics

            statistics = self._calculate_statistics(user)
            cache.set(cache_key, statistics, timeout=self.cache_timeout)

            logger.debug(
                'Statistics calculated and cached',
                user_id=user.id,
                cache_key=cache_key,
            )

        except DatabaseError as e:
            logger.exception(
                'Database error while getting user statistics',
                user_id=user.id,
                error=str(e),
            )
            raise

        return statistics

    def _calculate_statistics(self, user: User) -> UserStatistics:
        """Calculate user statistics.

        Args:
            user: User to calculate statistics for.

        Returns:
            UserStatistics: Dictionary with user statistics.
        """
        period_dates = self._calculate_period_dates()

        accounts_stats = self._get_accounts_statistics(user)
        expenses_stats = self._get_expenses_statistics(
            user,
            period_dates['month_start'],
            period_dates['last_month_start'],
            period_dates['last_month_end'],
        )
        income_stats = self._get_income_statistics(
            user,
            period_dates['month_start'],
            period_dates['last_month_start'],
            period_dates['last_month_end'],
        )
        recent_transactions = self._get_recent_transactions(user)
        top_categories = self._get_top_categories(
            user,
            period_dates['month_start'],
        )

        receipts_count = self.statistics_repository.get_receipts_count(user)

        monthly_savings = income_stats['current'] - expenses_stats['current']
        last_month_savings = (
            income_stats['last_month'] - expenses_stats['last_month']
        )

        return {
            'total_balance': to_decimal(accounts_stats['total_balance']),
            'accounts_count': int(accounts_stats['accounts_count']),
            'current_month_expenses': to_decimal(expenses_stats['current']),
            'current_month_income': to_decimal(income_stats['current']),
            'last_month_expenses': to_decimal(expenses_stats['last_month']),
            'last_month_income': to_decimal(income_stats['last_month']),
            'recent_expenses': list(recent_transactions['expenses']),
            'recent_incomes': list(recent_transactions['incomes']),
            'receipts_count': receipts_count,
            'top_expense_categories': list(top_categories),
            'monthly_savings': to_decimal(monthly_savings),
            'last_month_savings': to_decimal(last_month_savings),
        }

    def _calculate_period_dates(
        self,
    ) -> dict[str, datetime]:
        """Calculate period dates for statistics.

        Returns:
            Dictionary with keys:
            - 'month_start': datetime of current month start
            - 'last_month_start': datetime of last month start
            - 'last_month_end': datetime of last month end
        """
        today = timezone.now().date()
        month_start_date, _ = get_month_start_end(today)
        last_month_start_date, last_month_end_date = get_last_month_start_end(
            today
        )

        month_start = timezone.make_aware(
            datetime.combine(month_start_date, time.min),
        )
        last_month_start = timezone.make_aware(
            datetime.combine(last_month_start_date, time.min),
        )
        last_month_end = timezone.make_aware(
            datetime.combine(last_month_end_date, time.max),
        )

        return {
            'month_start': month_start,
            'last_month_start': last_month_start,
            'last_month_end': last_month_end,
        }

    def _get_accounts_statistics(
        self,
        user: User,
    ) -> dict[str, Decimal | int]:
        """Get account statistics for user.

        Args:
            user: User to get statistics for.

        Returns:
            Dictionary with 'total_balance' and 'accounts_count' keys.
        """
        return self.statistics_repository.get_accounts_aggregate(user)

    def _get_expenses_statistics(
        self,
        user: User,
        month_start: datetime,
        last_month_start: datetime,
        last_month_end: datetime,
    ) -> dict[str, Decimal]:
        """Get expense statistics for periods.

        Args:
            user: User to get statistics for.
            month_start: Start of current month.
            last_month_start: Start of last month.
            last_month_end: End of last month.

        Returns:
            Dictionary with 'current' and 'last_month' keys.
        """
        current_expenses = (
            self.statistics_repository.get_expenses_sum_by_period(
                user,
                month_start,
            )
        )
        last_month_expenses = (
            self.statistics_repository.get_expenses_sum_by_period(
                user,
                last_month_start,
                last_month_end,
            )
        )

        return {
            'current': current_expenses,
            'last_month': last_month_expenses,
        }

    def _get_income_statistics(
        self,
        user: User,
        month_start: datetime,
        last_month_start: datetime,
        last_month_end: datetime,
    ) -> dict[str, Decimal]:
        """Get income statistics for periods.

        Args:
            user: User to get statistics for.
            month_start: Start of current month.
            last_month_start: Start of last month.
            last_month_end: End of last month.

        Returns:
            Dictionary with 'current' and 'last_month' keys.
        """
        current_income = self.statistics_repository.get_income_sum_by_period(
            user,
            month_start,
        )
        last_month_income = self.statistics_repository.get_income_sum_by_period(
            user,
            last_month_start,
            last_month_end,
        )

        return {
            'current': current_income,
            'last_month': last_month_income,
        }

    def _get_recent_transactions(
        self,
        user: User,
    ) -> dict[str, list[Expense] | list[Income]]:
        """Get recent transactions for user.

        Args:
            user: User to get transactions for.

        Returns:
            Dictionary with 'expenses' and 'incomes' keys.
        """
        recent_expenses = self.statistics_repository.get_recent_expenses(
            user,
            limit=constants.RECENT_ITEMS_LIMIT,
        )
        recent_incomes = self.statistics_repository.get_recent_incomes(
            user,
            limit=constants.RECENT_ITEMS_LIMIT,
        )

        return {
            'expenses': recent_expenses,
            'incomes': recent_incomes,
        }

    def _get_top_categories(
        self,
        user: User,
        month_start: datetime,
    ) -> list[dict[str, str | Decimal]]:
        """Get top expense categories for current month.

        Args:
            user: User to get categories for.
            month_start: Start of current month.

        Returns:
            List of dictionaries with expense category data.
        """
        return list(
            self.statistics_repository.get_top_expense_categories(
                user,
                month_start,
                limit=constants.RECENT_ITEMS_LIMIT,
            ),
        )

    def _get_cache_key(self, user: User) -> str:
        """Get cache key for user statistics.

        Args:
            user: User to generate key for.

        Returns:
            Cache key in format 'user_statistics_{user_id}_{month}'.
        """
        today = timezone.now().date()
        current_month = today.strftime('%Y-%m')
        return f'user_statistics_{user.id}_{current_month}'

    def invalidate_cache(self, user: User) -> None:
        """Invalidate user statistics cache.

        Args:
            user: User to invalidate cache for.
        """
        cache_key = self._get_cache_key(user)
        cache.delete(cache_key)
        logger.debug(
            'Statistics cache invalidated',
            user_id=user.id,
            cache_key=cache_key,
        )


def get_user_statistics(user: User) -> UserStatistics:
    """Get user statistics (legacy function).

    Function for backward compatibility. Creates service and repository
    directly. For new code, use DI container instead.

    Args:
        user: User to get statistics for.

    Returns:
        UserStatistics: Dictionary with user statistics.

    Raises:
        ValueError: If user is invalid.
        DatabaseError: On database errors.
    """
    repository = StatisticsRepository()
    service = UserStatisticsService(statistics_repository=repository)
    return service.get_user_statistics(user)
