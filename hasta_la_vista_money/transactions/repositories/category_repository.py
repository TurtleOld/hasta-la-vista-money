"""Django repository for the unified Category model."""

from django.db.models import QuerySet

from hasta_la_vista_money.transactions.models import Category
from hasta_la_vista_money.users.models import User


class CategoryRepository:
    """Repository for Category model operations."""

    def get_by_id(self, category_id: int) -> Category:
        """Return the category with the given primary key."""
        return Category.objects.get(pk=category_id)

    def get_by_user(
        self,
        user: User,
        type_value: str | None = None,
    ) -> QuerySet[Category]:
        """Return categories for a user, optionally filtered by type."""
        qs = user.categories.select_related('user').all()
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return qs

    def get_by_user_with_related(
        self,
        user: User,
        type_value: str | None = None,
    ) -> QuerySet[Category]:
        """Return categories for a user with ``parent_category`` preloaded."""
        qs = user.categories.select_related('user', 'parent_category').all()
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return qs

    def get_by_user_ordered(
        self,
        user: User,
        type_value: str | None = None,
    ) -> QuerySet[Category]:
        """Return categories ordered for form rendering."""
        qs = (
            user.categories.select_related('user', 'parent_category')
            .order_by('parent_category__name', 'name')
            .all()
        )
        if type_value is not None:
            qs = qs.filter(type=type_value)
        return qs

    def create_category(self, **kwargs: object) -> Category:
        """Create a category."""
        return Category.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Category]:
        """Filter categories by arbitrary criteria."""
        return Category.objects.filter(**kwargs)
