"""Django repository for Planning model.

This module provides data access layer for Planning model,
including filtering by user, date, type, and category.
"""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.transactions.models import Category
from hasta_la_vista_money.users.models import User


class PlanningRepository:
    """Repository for Planning model operations.

    Provides methods for accessing and manipulating planning data,
    including filtering by user, date ranges, types, and categories.
    """

    def get_by_id(self, planning_id: int) -> Planning:
        """Get planning by ID."""
        return Planning.objects.get(pk=planning_id)

    def get_by_user(self, user: User) -> QuerySet[Planning]:
        """Get all plannings for a user."""
        return Planning.objects.for_user(user)

    def get_by_user_with_related(self, user: User) -> QuerySet[Planning]:
        """Get all plannings for a user with related objects optimized."""
        return Planning.objects.for_user(user).with_related()

    def get_expenses_by_user(self, user: User) -> QuerySet[Planning]:
        """Get all expense plannings for a user."""
        return Planning.objects.for_user(user).expenses()

    def get_incomes_by_user(self, user: User) -> QuerySet[Planning]:
        """Get all income plannings for a user."""
        return Planning.objects.for_user(user).incomes()

    def get_by_period(
        self,
        user: User,
        start: date,
        end: date,
    ) -> QuerySet[Planning]:
        """Get plannings for a user within a date period."""
        return Planning.objects.for_user(user).for_period(start, end)

    def get_or_create_planning(
        self,
        defaults: dict[str, object] | None = None,
        **kwargs: object,
    ) -> tuple[Planning, bool]:
        """Get or create planning.

        Args:
            defaults: Dictionary of field values to set if creating.
            **kwargs: Lookup criteria (user, category, date, planning_type).

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
        """Create multiple plannings in a single database query."""
        return Planning.objects.bulk_create(plannings)

    def create_planning(self, **kwargs: object) -> Planning:
        """Create a new planning."""
        return Planning.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Planning]:
        """Filter plannings by given criteria."""
        return Planning.objects.filter(**kwargs)

    def filter_by_user_date_and_type(
        self,
        user: User,
        month: date,
        planning_type: str,
    ) -> QuerySet[Planning]:
        """Filter plannings by user, date, and type."""
        return Planning.objects.filter(
            user=user,
            date=month,
            planning_type=planning_type,
        ).select_related('user', 'category')

    def filter_by_user_category_and_month(
        self,
        user: User,
        category: Category,
        month: date,
        planning_type: str,
    ) -> Planning | None:
        """Get planning by user, category, and month."""
        qs = self.filter_by_user_date_and_type(user, month, planning_type)
        return qs.filter(category=category).first()
