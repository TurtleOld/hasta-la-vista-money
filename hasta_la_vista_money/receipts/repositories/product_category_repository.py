"""Django repository for the product category directory."""

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import QuerySet

from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import ProductCategory
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_category_name,
)
from hasta_la_vista_money.users.models import User


class ProductCategoryRepository:
    """Persist normalized product categories and starter directories."""

    def get_or_create_category(
        self,
        *,
        user: User,
        name: str,
    ) -> ProductCategory:
        """Return a user's category with a normalized, unique name."""
        display_name = ' '.join(name.split())
        normalized_name = normalize_product_category_name(display_name)
        category, _ = ProductCategory.objects.get_or_create(
            user=user,
            normalized_name=normalized_name,
            defaults={'name': display_name},
        )
        return category

    def get_by_name(
        self,
        *,
        user: User,
        name: str,
    ) -> ProductCategory | None:
        """Return a category after applying directory normalization."""
        normalized_name = normalize_product_category_name(name)
        return ProductCategory.objects.filter(
            user=user,
            normalized_name=normalized_name,
        ).first()

    def list_for_user(self, user: User) -> QuerySet[ProductCategory]:
        """Return the user's complete product-category directory."""
        return ProductCategory.objects.filter(user=user).order_by('name')

    def find_similar_by_name(
        self,
        *,
        user: User,
        name: str,
        minimum_similarity: float,
    ) -> ProductCategory | None:
        """Return the closest category above the supplied name threshold."""
        normalized_name = normalize_product_category_name(name)
        return (
            ProductCategory.objects.filter(user=user)
            .annotate(
                similarity=TrigramSimilarity(
                    'normalized_name',
                    normalized_name,
                ),
            )
            .filter(similarity__gte=minimum_similarity)
            .order_by('-similarity', 'name')
            .first()
        )

    def rename_category(self, category: ProductCategory, name: str) -> None:
        """Rename a category while preserving its normalized-name invariant."""
        category.name = ' '.join(name.split())
        category.normalized_name = normalize_product_category_name(
            category.name,
        )
        category.save(update_fields=['name', 'normalized_name'])

    def seed_starter_categories(self, user: User) -> None:
        """Create any missing standard product categories for a user."""
        for name in constants.STARTER_PRODUCT_CATEGORIES:
            self.get_or_create_category(user=user, name=name)
