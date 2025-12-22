"""Репозиторий для работы со статистикой пользователей.

Модуль предоставляет методы для агрегации данных статистики,
включая работу с расходами, доходами, счетами и чеками.
"""

from datetime import datetime
from decimal import Decimal

from django.db.models import Count, QuerySet, Sum

from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


class StatisticsRepository:
    """Репозиторий для работы со статистикой пользователей.

    Предоставляет методы для агрегации данных по расходам, доходам,
    счетам и чекам пользователя.
    """

    def get_accounts_aggregate(
        self,
        user: User,
    ) -> dict[str, Decimal | int]:
        """Получить агрегированные данные по счетам пользователя.

        Args:
            user: Пользователь для получения статистики.

        Returns:
            Словарь с ключами:
            - 'total_balance': Decimal - общий баланс всех счетов
            - 'accounts_count': int - количество счетов
        """
        accounts_qs = Account.objects.filter(user=user)
        accounts_data = accounts_qs.aggregate(
            total_balance=Sum('balance'),
            accounts_count=Count('id'),
        )
        return {
            'total_balance': accounts_data['total_balance'] or Decimal(0),
            'accounts_count': accounts_data['accounts_count'] or 0,
        }

    def get_expenses_sum_by_period(
        self,
        user: User,
        start_date: datetime,
        end_date: datetime | None = None,
    ) -> Decimal:
        """Получить сумму расходов за период.

        Args:
            user: Пользователь для получения статистики.
            start_date: Начало периода (включительно).
            end_date: Конец периода (включительно). Если None,
                используется текущее время.

        Returns:
            Decimal: Сумма расходов за период.
        """
        qs = Expense.objects.filter(user=user, date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)
        result = qs.aggregate(total=Sum('amount'))['total']
        return result or Decimal(0)

    def get_income_sum_by_period(
        self,
        user: User,
        start_date: datetime,
        end_date: datetime | None = None,
    ) -> Decimal:
        """Получить сумму доходов за период.

        Args:
            user: Пользователь для получения статистики.
            start_date: Начало периода (включительно).
            end_date: Конец периода (включительно). Если None,
                используется текущее время.

        Returns:
            Decimal: Сумма доходов за период.
        """
        qs = Income.objects.filter(user=user, date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)
        result = qs.aggregate(total=Sum('amount'))['total']
        return result or Decimal(0)

    def get_recent_expenses(
        self,
        user: User,
        limit: int = 5,
    ) -> QuerySet[Expense]:
        """Получить последние расходы пользователя.

        Args:
            user: Пользователь для получения статистики.
            limit: Максимальное количество записей.

        Returns:
            QuerySet[Expense]: QuerySet последних расходов с оптимизацией
                select_related для category и account.
        """
        return (
            Expense.objects.filter(user=user)
            .select_related('category', 'account')
            .order_by('-date')[:limit]
        )

    def get_recent_incomes(
        self,
        user: User,
        limit: int = 5,
    ) -> QuerySet[Income]:
        """Получить последние доходы пользователя.

        Args:
            user: Пользователь для получения статистики.
            limit: Максимальное количество записей.

        Returns:
            QuerySet[Income]: QuerySet последних доходов с оптимизацией
                select_related для category и account.
        """
        return (
            Income.objects.filter(user=user)
            .select_related('category', 'account')
            .order_by('-date')[:limit]
        )

    def get_receipts_count(self, user: User) -> int:
        """Получить количество чеков пользователя.

        Args:
            user: Пользователь для получения статистики.

        Returns:
            int: Количество чеков пользователя.
        """
        return Receipt.objects.filter(user=user).count()

    def get_top_expense_categories(
        self,
        user: User,
        start_date: datetime,
        limit: int = 5,
    ) -> QuerySet[Expense, dict[str, str | Decimal]]:
        """Получить топ категорий расходов за период.

        Args:
            user: Пользователь для получения статистики.
            start_date: Начало периода для фильтрации.
            limit: Максимальное количество категорий.

        Returns:
            QuerySet[Expense, dict[str, str | Decimal]]: QuerySet с
                агрегированными данными по категориям, отсортированный
                по сумме расходов по убыванию.
        """
        return (
            Expense.objects.filter(user=user, date__gte=start_date)
            .values('category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:limit]
        )
