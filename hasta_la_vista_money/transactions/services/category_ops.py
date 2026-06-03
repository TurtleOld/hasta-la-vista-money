"""Business logic for unified Category operations."""

from typing import TYPE_CHECKING

from django.core.cache import cache

from hasta_la_vista_money.transactions.forms import CategoryForm
from hasta_la_vista_money.transactions.models import Category
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.transactions.repositories.category_repository import (  # noqa: E501
        CategoryRepository,
    )


CATEGORY_TREE_CACHE_DEPTHS = range(1, 6)


class CategoryService:
    """Service for creating and updating user categories."""

    def __init__(
        self,
        category_repository: 'CategoryRepository',
    ) -> None:
        self.category_repository = category_repository

    @staticmethod
    def _invalidate_tree_cache(user: User, type_value: str) -> None:
        for depth in CATEGORY_TREE_CACHE_DEPTHS:
            cache.delete(f'category_tree_{type_value}_{user.pk}_{depth}')

    def create_category(self, user: User, form: CategoryForm) -> Category:
        """Create a category from a validated form."""
        instance = form.save(commit=False)
        new_category = self.category_repository.create_category(
            user=user,
            name=instance.name,
            type=instance.type,
            parent_category=instance.parent_category,
        )
        self._invalidate_tree_cache(user, new_category.type)
        return new_category

    def update_category(
        self,
        user: User,
        category: Category,
        form: CategoryForm,
    ) -> Category:
        """Update an existing category from a validated form."""
        category.name = form.cleaned_data['name']
        category.parent_category = form.cleaned_data.get('parent_category')
        if 'type' in form.cleaned_data:
            category.type = form.cleaned_data['type']
        category.save()
        self._invalidate_tree_cache(user, category.type)
        return category
