"""Django repository for IncomeCategory model.

This module provides data access layer for IncomeCategory model,
including filtering and CRUD operations.
"""

from django.db.models import QuerySet

from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeCategoryRepository:
    """Repository for IncomeCategory model operations.

    Provides methods for accessing and manipulating income category data.
    """

    def get_by_id(self, category_id: int) -> IncomeCategory:
        """Get category by ID.

        Args:
            category_id: ID of the category to retrieve.

        Returns:
            IncomeCategory: Category instance.

        Raises:
            IncomeCategory.DoesNotExist: If category with given ID
                doesn't exist.
        """
        return IncomeCategory.objects.get(pk=category_id)

    def get_by_user(self, user: User) -> QuerySet[IncomeCategory]:
        """Get all categories for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[IncomeCategory]: QuerySet of user's categories.
        """
        return IncomeCategory.objects.filter(user=user)

    def get_by_user_with_related(self, user: User) -> QuerySet[IncomeCategory]:
        """Get all categories for a user with related objects optimized.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[IncomeCategory]: QuerySet with select_related
                optimizations.
        """
        return IncomeCategory.objects.filter(user=user).select_related(
            'user', 'parent_category'
        )

    def get_by_user_ordered(self, user: User) -> QuerySet[IncomeCategory]:
        """Get all categories for a user ordered by parent category.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[IncomeCategory]: QuerySet ordered by parent_category_id.
        """
        return (
            IncomeCategory.objects.filter(user=user)
            .select_related('user', 'parent_category')
            .order_by('parent_category_id')
        )

    def create_category(self, **kwargs: object) -> IncomeCategory:
        """Create a new category.

        Args:
            **kwargs: Category field values (user, name, parent_category).

        Returns:
            IncomeCategory: Created category instance.
        """
        return IncomeCategory.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[IncomeCategory]:
        """Filter categories by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[IncomeCategory]: Filtered QuerySet.
        """
        return IncomeCategory.objects.filter(**kwargs)
