"""Django repository for Expense model.

This module provides data access layer for Expense model,
including filtering, aggregation, and CRUD operations.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth

from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.models import ExpenseCategory


class ExpenseRepository:
    """Repository for Expense model operations.

    Provides methods for accessing and manipulating expense data,
    including filtering by user, date ranges, categories, and groups.
    """

    def get_by_id(self, expense_id: int) -> Expense:
        """Get expense by ID.

        Args:
            expense_id: ID of the expense to retrieve.

        Returns:
            Expense: Expense instance.

        Raises:
            Expense.DoesNotExist: If expense with given ID doesn't exist.
        """
        return Expense.objects.get(pk=expense_id)

    def get_by_user(self, user: User) -> QuerySet[Expense]:
        """Get all expenses for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Expense]: QuerySet of expenses with related objects
                (user, category, account) optimized.
        """
        return Expense.objects.filter(user=user).select_related(
            'user',
            'category',
            'account',
        )

    def get_by_user_and_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> QuerySet[Expense]:
        """Get expenses for user or group.

        Args:
            user: User instance to filter by.
            group_id: Group ID to filter by. If None or 'my',
                returns only user's expenses.

        Returns:
            QuerySet[Expense]: QuerySet of expenses filtered by user/group.
        """
        if not group_id or group_id == 'my':
            return Expense.objects.filter(user=user).select_related(
                'user',
                'category',
                'account',
            )

        user_with_groups = User.objects.prefetch_related('groups').get(
            pk=user.pk,
        )
        if user_with_groups.groups.filter(id=group_id).exists():
            group_users = list(User.objects.filter(groups__id=group_id))
            return Expense.objects.filter(user__in=group_users).select_related(
                'user',
                'category',
                'account',
            )

        return Expense.objects.none()

    def create_expense(self, **kwargs: object) -> Expense:
        """Create a new expense.

        Args:
            **kwargs: Expense field values (user, account, category,
                amount, date).

        Returns:
            Expense: Created expense instance.
        """
        return Expense.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Expense]:
        """Filter expenses by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Expense]: Filtered QuerySet.
        """
        return Expense.objects.filter(**kwargs)

    def filter_by_user_and_date_range(
        self,
        user: User,
        start_date: datetime,
        end_date: datetime,
    ) -> QuerySet[Expense]:
        """Filter expenses by user and date range.

        Args:
            user: User instance to filter by.
            start_date: Start of date range (inclusive).
            end_date: End of date range (inclusive).

        Returns:
            QuerySet[Expense]: Filtered QuerySet.
        """
        return Expense.objects.filter(
            user=user,
            date__gte=start_date,
            date__lte=end_date,
        )

    def filter_by_user_and_account(
        self,
        user: User,
        account: Account,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> QuerySet[Expense, dict[str, Any]]:
        """Filter expenses by user, account, and optional date range.

        Returns aggregated data grouped by month.

        Args:
            user: User instance to filter by.
            account: Account instance to filter by.
            start_date: Optional start of date range.
            end_date: Optional end of date range.

        Returns:
            QuerySet[Expense, dict[str, Any]]: Aggregated QuerySet with
                month and total fields.
        """
        qs = Expense.objects.filter(user=user, account=account)
        if start_date:
            qs = qs.filter(date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)
        return (
            qs.annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total=Sum('amount'))
        )

    def get_aggregated_by_date(
        self,
        user: User,
    ) -> QuerySet[Expense, dict[str, Any]]:
        """Get aggregated expenses grouped by date.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Expense, dict[str, Any]]: Aggregated QuerySet with
                date and total_amount fields, ordered by date.
        """
        return (
            Expense.objects.filter(user=user)
            .values('date')
            .annotate(total_amount=Sum('amount'))
            .order_by('date')
        )

    def get_top_categories(
        self,
        user: User,
        year_start: datetime,
        limit: int = 10,
    ) -> QuerySet[Expense, dict[str, Any]]:
        """Get top expense categories by total amount.

        Args:
            user: User instance to filter by.
            year_start: Start date for filtering (typically start of year).
            limit: Maximum number of categories to return.

        Returns:
            QuerySet[Expense, dict[str, Any]]: Aggregated QuerySet with
                category__name and total fields, ordered by total descending.
        """
        return (
            Expense.objects.filter(user=user, date__gte=year_start)
            .values('category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:limit]
        )

    def filter_by_user_category_and_month(
        self,
        user: User,
        category: 'ExpenseCategory',
        month: date,
    ) -> QuerySet[Expense]:
        """Filter expenses by user, category, and month.

        Args:
            user: User instance to filter by.
            category: ExpenseCategory instance to filter by.
            month: Date object representing the month to filter by.

        Returns:
            QuerySet[Expense]: Filtered QuerySet with related objects optimized.
        """
        return Expense.objects.filter(
            user=user,
            category=category,
            date__year=month.year,
            date__month=month.month,
        ).select_related('user', 'category')
