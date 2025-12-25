"""Django repository for user statistics.

This module provides methods for aggregating statistics data,
including work with expenses, income, accounts, and receipts.
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
    """Repository for user statistics operations.

    Provides methods for aggregating data on expenses, income,
    accounts, and receipts for users.
    """

    def get_accounts_aggregate(
        self,
        user: User,
    ) -> dict[str, Decimal | int]:
        """Get aggregated account data for user.

        Args:
            user: User to get statistics for.

        Returns:
            Dictionary with keys:
            - 'total_balance': Decimal - total balance of all accounts
            - 'accounts_count': int - number of accounts
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
        """Get total expenses sum for period.

        Args:
            user: User to get statistics for.
            start_date: Period start (inclusive).
            end_date: Period end (inclusive). If None, uses current time.

        Returns:
            Decimal: Total expenses sum for the period.
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
        """Get total income sum for period.

        Args:
            user: User to get statistics for.
            start_date: Period start (inclusive).
            end_date: Period end (inclusive). If None, uses current time.

        Returns:
            Decimal: Total income sum for the period.
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
        """Get recent expenses for user.

        Args:
            user: User to get expenses for.
            limit: Maximum number of records.

        Returns:
            QuerySet[Expense]: QuerySet of recent expenses with select_related
                optimization for category and account.
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
        """Get recent income for user.

        Args:
            user: User to get income for.
            limit: Maximum number of records.

        Returns:
            QuerySet[Income]: QuerySet of recent income with select_related
                optimization for category and account.
        """
        return (
            Income.objects.filter(user=user)
            .select_related('category', 'account')
            .order_by('-date')[:limit]
        )

    def get_receipts_count(self, user: User) -> int:
        """Get receipts count for user.

        Args:
            user: User to get count for.

        Returns:
            int: Number of receipts for user.
        """
        return Receipt.objects.filter(user=user).count()

    def get_top_expense_categories(
        self,
        user: User,
        start_date: datetime,
        limit: int = 5,
    ) -> QuerySet[Expense, dict[str, str | Decimal]]:
        """Get top expense categories for period.

        Args:
            user: User to get categories for.
            start_date: Period start for filtering.
            limit: Maximum number of categories.

        Returns:
            QuerySet[Expense, dict[str, str | Decimal]]: QuerySet with
                aggregated category data, sorted by expense amount descending.
        """
        return (
            Expense.objects.filter(user=user, date__gte=start_date)
            .values('category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:limit]
        )
