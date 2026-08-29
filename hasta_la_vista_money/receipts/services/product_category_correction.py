"""Persist human product-category corrections as pinned name mappings.

A human correction pins a product name to a category, so the same product in
a future receipt lands in the right category automatically. At the same time
it reclassifies the owner's already-saved rows with the same normalized name
that were not put there by a human.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hasta_la_vista_money.receipts.models import ProductCategorySource
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from hasta_la_vista_money.receipts.models import ProductCategory
    from hasta_la_vista_money.receipts.repositories.product_name_category_mapping_repository import (  # noqa: E501
        ProductNameCategoryMappingRepository,
    )
    from hasta_la_vista_money.receipts.repositories.product_repository import (
        ProductRepository,
    )
    from hasta_la_vista_money.users.models import User


class ProductCategoryCorrectionService:
    """Remember a human category correction and apply it retroactively."""

    def __init__(
        self,
        mapping_repository: ProductNameCategoryMappingRepository,
        product_repository: ProductRepository,
    ) -> None:
        """Initialize the service.

        Args:
            mapping_repository: Repository for pinned name mappings.
            product_repository: Repository for product data access.
        """
        self.mapping_repository = mapping_repository
        self.product_repository = product_repository

    def apply_correction(
        self,
        *,
        user: User,
        product_name: str,
        category: ProductCategory | None,
        exclude_product_ids: Iterable[int] = (),
    ) -> None:
        """Pin a corrected category and reclassify the owner's other rows.

        The corrected name is pinned to the given category. Every other
        product row of the same owner with the same normalized name and a
        non-manual source is reclassified to that category, so past receipts
        reflect the correction retroactively. Rows the owner set manually
        are never touched.

        Args:
            user: Owner of the correction.
            product_name: The product name being corrected.
            category: The category the human chose, or ``None`` to skip.
            exclude_product_ids: Product primary keys to leave untouched,
                typically the rows of the receipt currently being edited.
        """
        if category is None:
            return
        normalized_name = normalize_product_name(product_name)
        if not normalized_name:
            return

        self.mapping_repository.upsert(
            user=user,
            normalized_product_name=normalized_name,
            category=category,
        )
        self.product_repository.reclassify_by_normalized_name(
            user=user,
            normalized_product_name=normalized_name,
            category=category,
            source=ProductCategorySource.NAME_MATCH,
            exclude_ids=exclude_product_ids,
        )


__all__ = ['ProductCategoryCorrectionService']
