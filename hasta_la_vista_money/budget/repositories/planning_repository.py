"""Django repository for Planning model.

This module provides data access layer for Planning model,
including filtering by user, date, type, and category.
"""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.users.models import User


class PlanningRepository:
    """Repository for Planning model operations.

    Provides methods for accessing and manipulating planning data,
    including filtering by user, date ranges, types, and categories.
    """

    def get_by_id(self, planning_id: int) -> Planning:
        """Get planning by ID.

        Args:
            planning_id: ID of the planning to retrieve.

        Returns:
            Planning: Planning instance.

        Raises:
            Planning.DoesNotExist: If planning with given ID doesn't exist.
        """
        return Planning.objects.get(pk=planning_id)

    def get_by_user(self, user: User) -> QuerySet[Planning]:
        """Get all plannings for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Planning]: QuerySet of user's plannings.
        """
        return Planning.objects.for_user(user)

    def get_by_user_with_related(self, user: User) -> QuerySet[Planning]:
        """Get all plannings for a user with related objects optimized.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Planning]: QuerySet with select_related optimizations.
        """
        return Planning.objects.for_user(user).with_related()

    def get_expenses_by_user(self, user: User) -> QuerySet[Planning]:
        """Get all expense plannings for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Planning]: QuerySet filtered to expense plannings only.
        """
        return Planning.objects.for_user(user).expenses()

    def get_incomes_by_user(self, user: User) -> QuerySet[Planning]:
        """Get all income plannings for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Planning]: QuerySet filtered to income plannings only.
        """
        return Planning.objects.for_user(user).incomes()

    def get_by_period(
        self,
        user: User,
        start: date,
        end: date,
    ) -> QuerySet[Planning]:
        """Get plannings for a user within a date period.

        Args:
            user: User instance to filter by.
            start: Start of date range (inclusive).
            end: End of date range (inclusive).

        Returns:
            QuerySet[Planning]: Filtered QuerySet.
        """
        return Planning.objects.for_user(user).for_period(start, end)

    def get_or_create_planning(
        self,
        defaults: dict[str, object] | None = None,
        **kwargs: object,
    ) -> tuple[Planning, bool]:
        """Get or create planning.

        Args:
            defaults: Dictionary of field values to set if creating.
            **kwargs: Lookup criteria (user, category_expense/category_income,
                date, planning_type).

        Returns:
            tuple[Planning, bool]: Tuple of (planning instance, created flag).
        """
        return Planning.objects.get_or_create(
            defaults=defaults or {},
            **kwargs,
        )

    def bulk_create_plannings(
        self,
        plannings: list[Planning],
    ) -> list[Planning]:
        """Create multiple plannings in a single database query.

        Args:
            plannings: List of Planning instances to create.

        Returns:
            list[Planning]: List of created planning instances.
        """
        return Planning.objects.bulk_create(plannings)

    def create_planning(self, **kwargs: object) -> Planning:
        """Create a new planning.

        Args:
            **kwargs: Planning field values (
                user, category_expense/category_income,
                date, amount, planning_type).

        Returns:
            Planning: Created planning instance.
        """
        return Planning.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Planning]:
        """Filter plannings by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Planning]: Filtered QuerySet.
        """
        return Planning.objects.filter(**kwargs)

    def filter_by_user_date_and_type(
        self,
        user: User,
        month: date,
        planning_type: str,
    ) -> QuerySet[Planning]:
        """Filter plannings by user, date, and type.

        Args:
            user: User instance to filter by.
            month: Date object representing the month to filter by.
            planning_type: Planning type ('expense' or 'income').

        Returns:
            QuerySet[Planning]: Filtered QuerySet with related objects
                optimized.
        """
        return Planning.objects.filter(
            user=user,
            date=month,
            planning_type=planning_type,
        ).select_related('user', 'category_expense', 'category_income')

    def filter_by_user_category_and_month(
        self,
        user: User,
        category: ExpenseCategory | IncomeCategory,
        month: date,
        planning_type: str,
    ) -> Planning | None:
        """Get planning by user, category, and month.

        Args:
            user: User instance to filter by.
            category: ExpenseCategory or IncomeCategory instance.
            month: Date object representing the month.
            planning_type: Planning type ('expense' or 'income').

        Returns:
            Planning | None: Planning instance if found, None otherwise.
        """
        qs = self.filter_by_user_date_and_type(user, month, planning_type)
        if planning_type == 'expense' and isinstance(category, ExpenseCategory):
            return qs.filter(category_expense=category).first()
        if planning_type == 'income' and isinstance(category, IncomeCategory):
            return qs.filter(category_income=category).first()
        return None
