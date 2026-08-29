"""Receipt item categorization: pinned name match, then writing match."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from django.conf import settings
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models.functions import Lower

from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategorySource,
    ProductNameCategoryMapping,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from hasta_la_vista_money.users.models import User

_WORD_RE: Final[re.Pattern[str]] = re.compile(r'[^0-9a-zа-яё]+')
_SPACE_RE: Final[re.Pattern[str]] = re.compile(r'\s+')


def normalize_product_name(value: str) -> str:
    """Normalize product name for pinned-mapping lookups."""
    normalized = value.lower().replace('ё', 'е')
    normalized = _WORD_RE.sub(' ', normalized)
    return _SPACE_RE.sub(' ', normalized).strip()


class ReceiptItemCategoryService:
    """Categorize receipt items: pinned name match, then writing match.

    A pinned mapping (:class:`ProductNameCategoryMapping`) always wins. If
    none exists, the category is picked from the owner's previously
    categorized products by database-side trigram similarity. If neither
    stage finds anything, the item falls back to the default category.
    """

    def categorize(self, *, user: User, product_name: str) -> str:
        """Return category name for a product name."""
        category, _source = self._categorize(
            user=user,
            product_name=product_name,
        )
        return category

    def categorize_items(
        self,
        *,
        user: User,
        items: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return item copies with missing/default categories filled in."""
        categorized_items: list[dict[str, Any]] = []
        for item in items:
            categorized_item = dict(item)
            existing_category = str(categorized_item.get('category') or '')
            if (
                not existing_category
                or existing_category == constants.DEFAULT_PRODUCT_CATEGORY
            ):
                product_name = str(categorized_item.get('product_name') or '')
                category, source = self._categorize(
                    user=user,
                    product_name=product_name,
                )
                categorized_item['category'] = category
                categorized_item['category_source'] = source.value
            categorized_items.append(categorized_item)
        return categorized_items

    def _categorize(
        self,
        *,
        user: User,
        product_name: str,
    ) -> tuple[str, ProductCategorySource]:
        normalized_name = normalize_product_name(product_name)
        if not normalized_name:
            return (
                constants.DEFAULT_PRODUCT_CATEGORY,
                ProductCategorySource.WRITING_MATCH,
            )

        pinned_category = self._pinned_category(user, normalized_name)
        if pinned_category is not None:
            return pinned_category, ProductCategorySource.NAME_MATCH

        writing_match_category = self._writing_match_category(
            user,
            normalized_name,
        )
        if writing_match_category is not None:
            return writing_match_category, ProductCategorySource.WRITING_MATCH

        return (
            constants.DEFAULT_PRODUCT_CATEGORY,
            ProductCategorySource.WRITING_MATCH,
        )

    def _pinned_category(
        self,
        user: User,
        normalized_name: str,
    ) -> str | None:
        mapping = (
            ProductNameCategoryMapping.objects.filter(
                user=user,
                normalized_product_name=normalized_name,
            )
            .select_related('category')
            .first()
        )
        return mapping.category.name if mapping else None

    def _writing_match_category(
        self,
        user: User,
        normalized_name: str,
    ) -> str | None:
        threshold = settings.RECEIPT_CATEGORY_WRITING_SIMILARITY_THRESHOLD
        match = (
            Product.objects.filter(user=user)
            .exclude(category__isnull=True)
            .annotate(
                similarity=TrigramSimilarity(
                    Lower('product_name'),
                    normalized_name,
                ),
            )
            .filter(similarity__gte=threshold)
            .select_related('category')
            .order_by('-similarity', '-created_at')
            .first()
        )
        return match.category.name if match and match.category else None


__all__ = [
    'ReceiptItemCategoryService',
    'normalize_product_name',
]
