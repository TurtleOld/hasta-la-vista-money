"""Сервис для получения статистики пользователя.

Модуль предоставляет сервис для расчета и получения статистики
пользователя, включая балансы, расходы, доходы и категории.
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
    """Статистика пользователя.

    Attributes:
        total_balance: Общий баланс всех счетов пользователя.
        accounts_count: Количество счетов пользователя.
        current_month_expenses: Сумма расходов за текущий месяц.
        current_month_income: Сумма доходов за текущий месяц.
        last_month_expenses: Сумма расходов за прошлый месяц.
        last_month_income: Сумма доходов за прошлый месяц.
        recent_expenses: Список последних расходов.
        recent_incomes: Список последних доходов.
        receipts_count: Количество чеков пользователя.
        top_expense_categories: Топ категорий расходов за текущий месяц.
        monthly_savings: Сбережения за текущий месяц (доходы - расходы).
        last_month_savings: Сбережения за прошлый месяц.
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
    """Сервис для получения статистики пользователя.

    Предоставляет методы для расчета различных метрик статистики
    пользователя с использованием репозиториев и кеширования.
    """

    def __init__(
        self,
        statistics_repository: StatisticsRepository,
    ) -> None:
        """Инициализация сервиса статистики.

        Args:
            statistics_repository: Репозиторий для работы со статистикой.
        """
        self.statistics_repository = statistics_repository
        self.cache_timeout = 300

    def get_user_statistics(self, user: User) -> UserStatistics:
        """Получить полную статистику пользователя.

        Метод получает статистику пользователя, включая балансы счетов,
        расходы и доходы за текущий и прошлый месяц, последние транзакции
        и топ категорий. Использует кеширование для оптимизации.

        Args:
            user: Пользователь для получения статистики.

        Returns:
            UserStatistics: Словарь со статистикой пользователя.

        Raises:
            ValueError: Если пользователь не валиден.
            DatabaseError: При ошибках работы с базой данных.
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
        """Рассчитать статистику пользователя.

        Args:
            user: Пользователь для расчета статистики.

        Returns:
            UserStatistics: Словарь со статистикой пользователя.
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
        """Рассчитать даты периодов для статистики.

        Returns:
            Словарь с ключами:
            - 'month_start': datetime начала текущего месяца
            - 'last_month_start': datetime начала прошлого месяца
            - 'last_month_end': datetime конца прошлого месяца
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
        """Получить статистику по счетам пользователя.

        Args:
            user: Пользователь для получения статистики.

        Returns:
            Словарь с ключами 'total_balance' и 'accounts_count'.
        """
        return self.statistics_repository.get_accounts_aggregate(user)

    def _get_expenses_statistics(
        self,
        user: User,
        month_start: datetime,
        last_month_start: datetime,
        last_month_end: datetime,
    ) -> dict[str, Decimal]:
        """Получить статистику по расходам за периоды.

        Args:
            user: Пользователь для получения статистики.
            month_start: Начало текущего месяца.
            last_month_start: Начало прошлого месяца.
            last_month_end: Конец прошлого месяца.

        Returns:
            Словарь с ключами 'current' и 'last_month'.
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
        """Получить статистику по доходам за периоды.

        Args:
            user: Пользователь для получения статистики.
            month_start: Начало текущего месяца.
            last_month_start: Начало прошлого месяца.
            last_month_end: Конец прошлого месяца.

        Returns:
            Словарь с ключами 'current' и 'last_month'.
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
        """Получить последние транзакции пользователя.

        Args:
            user: Пользователь для получения статистики.

        Returns:
            Словарь с ключами 'expenses' и 'incomes'.
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
        """Получить топ категорий расходов за текущий месяц.

        Args:
            user: Пользователь для получения статистики.
            month_start: Начало текущего месяца.

        Returns:
            Список словарей с данными о категориях расходов.
        """
        return list(
            self.statistics_repository.get_top_expense_categories(
                user,
                month_start,
                limit=constants.RECENT_ITEMS_LIMIT,
            ),
        )

    def _get_cache_key(self, user: User) -> str:
        """Получить ключ кеша для статистики пользователя.

        Args:
            user: Пользователь для генерации ключа.

        Returns:
            str: Ключ кеша в формате 'user_statistics_{user_id}_{month}'.
        """
        today = timezone.now().date()
        current_month = today.strftime('%Y-%m')
        return f'user_statistics_{user.id}_{current_month}'

    def invalidate_cache(self, user: User) -> None:
        """Инвалидировать кеш статистики пользователя.

        Args:
            user: Пользователь для инвалидации кеша.
        """
        cache_key = self._get_cache_key(user)
        cache.delete(cache_key)
        logger.debug(
            'Statistics cache invalidated',
            user_id=user.id,
            cache_key=cache_key,
        )


def get_user_statistics(user: User) -> UserStatistics:
    """Получить статистику пользователя (legacy функция).

    Функция для обратной совместимости. Создает сервис и репозиторий
    напрямую. Для новых кодов рекомендуется использовать DI контейнер.

    Args:
        user: Пользователь для получения статистики.

    Returns:
        UserStatistics: Словарь со статистикой пользователя.

    Raises:
        ValueError: Если пользователь не валиден.
        DatabaseError: При ошибках работы с базой данных.
    """
    repository = StatisticsRepository()
    service = UserStatisticsService(statistics_repository=repository)
    return service.get_user_statistics(user)
