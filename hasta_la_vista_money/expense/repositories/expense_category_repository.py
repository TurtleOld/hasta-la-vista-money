"""Django repository for ExpenseCategory model.

This module provides data access layer for ExpenseCategory model,
including filtering and CRUD operations.
"""

from django.db.models import QuerySet

from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.users.models import User


class ExpenseCategoryRepository:
    """Repository for ExpenseCategory model operations.

    Provides methods for accessing and manipulating expense category data.
    """

    def get_by_user(self, user: User) -> QuerySet[ExpenseCategory]:
        """Get all categories for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[ExpenseCategory]: QuerySet of categories ordered by
                parent category name and category name.
        """
        return (
            user.category_expense_users.select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

    def get_by_id(self, category_id: int) -> ExpenseCategory:
        """Get category by ID.

        Args:
            category_id: ID of the category to retrieve.

        Returns:
            ExpenseCategory: Category instance.

        Raises:
            ExpenseCategory.DoesNotExist: If category with given ID
                doesn't exist.
        """
        return ExpenseCategory.objects.get(pk=category_id)

    def create_category(self, **kwargs: object) -> ExpenseCategory:
        """Create a new category.

        Args:
            **kwargs: Category field values (user, name, parent_category).

        Returns:
            ExpenseCategory: Created category instance.
        """
        return ExpenseCategory.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[ExpenseCategory]:
        """Filter categories by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[ExpenseCategory]: Filtered QuerySet.
        """
        return ExpenseCategory.objects.filter(**kwargs)
