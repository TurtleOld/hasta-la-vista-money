"""Django repository for Income model.

This module provides data access layer for Income model,
including filtering, aggregation, and CRUD operations.
"""

from datetime import date, datetime, time
from typing import Any

from django.db.models import QuerySet, Sum
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeRepository:
    """Repository for Income model operations.

    Provides methods for accessing and manipulating income data,
    including filtering by user, date ranges, categories, and accounts.
    """

    def get_by_id(self, income_id: int) -> Income:
        """Get income by ID.

        Args:
            income_id: ID of the income to retrieve.

        Returns:
            Income: Income instance.

        Raises:
            Income.DoesNotExist: If income with given ID doesn't exist.
        """
        return Income.objects.get(pk=income_id)

    def get_by_user(self, user: User) -> QuerySet[Income]:
        """Get all incomes for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Income]: QuerySet of user's incomes.
        """
        return Income.objects.for_user(user)

    def get_by_user_with_related(self, user: User) -> QuerySet[Income]:
        """Get all incomes for a user with related objects optimized.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Income]: QuerySet with select_related optimizations
                applied.
        """
        return Income.objects.for_user(user).select_related(
            'user',
            'category',
            'account',
        )

    def get_by_period(
        self,
        user: User,
        start_date: date,
        end_date: date,
    ) -> QuerySet[Income]:
        """Get incomes for a user within a date period.

        Args:
            user: User instance to filter by.
            start_date: Start of date range (inclusive).
            end_date: End of date range (inclusive).

        Returns:
            QuerySet[Income]: Filtered QuerySet.
        """
        return Income.objects.for_user(user).for_period(start_date, end_date)

    def filter_by_user_and_date_range(
        self,
        user: User,
        start_date: datetime,
        end_date: datetime,
    ) -> QuerySet[Income]:
        """Filter incomes by user and datetime range.

        Args:
            user: User instance to filter by.
            start_date: Start of datetime range (inclusive).
            end_date: End of datetime range (inclusive).

        Returns:
            QuerySet[Income]: Filtered QuerySet.
        """
        return Income.objects.filter(
            user=user,
            date__gte=start_date,
            date__lte=end_date,
        )

    def get_by_category(
        self,
        user: User,
        category: IncomeCategory,
    ) -> QuerySet[Income]:
        """Get incomes for a user by category.

        Args:
            user: User instance to filter by.
            category: IncomeCategory instance to filter by.

        Returns:
            QuerySet[Income]: Filtered QuerySet.
        """
        return Income.objects.for_user(user).for_category(category)

    def get_by_account(
        self,
        user: User,
        account_id: int,
    ) -> QuerySet[Income]:
        """Get incomes for a user by account ID.

        Args:
            user: User instance to filter by.
            account_id: Account ID to filter by.

        Returns:
            QuerySet[Income]: Filtered QuerySet.
        """
        return Income.objects.for_user(user).filter(account_id=account_id)

    def create_income(self, **kwargs: object) -> Income:
        """Create a new income.

        Args:
            **kwargs: Income field values (user, account, category,
                amount, date).

        Returns:
            Income: Created income instance.
        """
        if 'date' in kwargs:
            date_value = kwargs['date']
            if isinstance(date_value, date) and not isinstance(date_value, datetime):
                kwargs['date'] = timezone.make_aware(
                    datetime.combine(date_value, time.min),
                )
            elif isinstance(date_value, datetime) and timezone.is_naive(date_value):
                kwargs['date'] = timezone.make_aware(date_value)
        return Income.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Income]:
        """Filter incomes by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Income]: Filtered QuerySet.
        """
        return Income.objects.filter(**kwargs)

    def filter_with_select_related(
        self,
        *related_fields: str,
        **kwargs: object,
    ) -> QuerySet[Income]:
        """Filter incomes with select_related optimization.

        Args:
            *related_fields: Field names to optimize with select_related.
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Income]: Filtered QuerySet with select_related applied.
        """
        return Income.objects.filter(**kwargs).select_related(*related_fields)

    def filter_by_account(
        self,
        account: Account,
    ) -> QuerySet[Income]:
        """Filter incomes by account.

        Args:
            account: Account instance to filter by.

        Returns:
            QuerySet[Income]: Filtered QuerySet ordered by date.
        """
        return Income.objects.filter(account=account).order_by('date')

    def get_aggregated_by_date(
        self,
        user: User,
    ) -> QuerySet[Income, dict[str, Any]]:
        """Get aggregated incomes grouped by date.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Income, dict[str, Any]]: Aggregated QuerySet with
                date and total_amount fields, ordered by date.
        """
        return (
            Income.objects.filter(user=user)
            .values('date')
            .annotate(total_amount=Sum('amount'))
            .order_by('date')
        )

    def get_top_categories(
        self,
        user: User,
        year_start: datetime,
        limit: int = 10,
    ) -> QuerySet[Income, dict[str, Any]]:
        """Get top income categories by total amount.

        Args:
            user: User instance to filter by.
            year_start: Start date for filtering (typically start of year).
            limit: Maximum number of categories to return.

        Returns:
            QuerySet[Income, dict[str, Any]]: Aggregated QuerySet with
                category__name and total fields, ordered by total descending.
        """
        return (
            Income.objects.filter(user=user, date__gte=year_start)
            .values('category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:limit]
        )

    def filter_by_user_category_and_month(
        self,
        user: User,
        category: IncomeCategory,
        month: date,
    ) -> QuerySet[Income]:
        """Filter incomes by user, category, and month.

        Args:
            user: User instance to filter by.
            category: IncomeCategory instance to filter by.
            month: Date object representing the month to filter by.

        Returns:
            QuerySet[Income]: Filtered QuerySet with related objects optimized.
        """
        return Income.objects.filter(
            user=user,
            category=category,
            date__year=month.year,
            date__month=month.month,
        ).select_related('user', 'category')
