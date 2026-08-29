"""Receipt item categorization: pinned, writing, then semantic match."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Final

from django.conf import settings
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models.functions import Lower
from pgvector.django import CosineDistance

from core.services.embedding import (
    EmbeddingProvider,
    EmbeddingServiceError,
    HttpEmbeddingProvider,
    NoopEmbeddingProvider,
)
from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategorySource,
    ProductNameCategoryMapping,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from hasta_la_vista_money.users.models import User

logger = logging.getLogger(__name__)

_WORD_RE: Final[re.Pattern[str]] = re.compile(r'[^0-9a-zа-яё]+')
_SPACE_RE: Final[re.Pattern[str]] = re.compile(r'\s+')
_EMBEDDING_BACKFILL_BATCH_SIZE: Final = 200


def normalize_product_name(value: str) -> str:
    """Normalize product name for pinned-mapping lookups."""
    normalized = value.lower().replace('ё', 'е')
    normalized = _WORD_RE.sub(' ', normalized)
    return _SPACE_RE.sub(' ', normalized).strip()


def build_embedding_provider() -> EmbeddingProvider:
    """Build the embedding provider configured for receipt categorization.

    Returns:
        ``HttpEmbeddingProvider`` if ``RECEIPT_CATEGORY_EMBEDDING_BASE_URL``
        is set, otherwise ``NoopEmbeddingProvider`` (semantic stage disabled).
    """
    base_url = getattr(settings, 'RECEIPT_CATEGORY_EMBEDDING_BASE_URL', '')
    if not base_url:
        return NoopEmbeddingProvider()
    return HttpEmbeddingProvider(
        base_url=base_url,
        api_key=getattr(settings, 'RECEIPT_CATEGORY_EMBEDDING_API_KEY', ''),
        model=getattr(settings, 'RECEIPT_CATEGORY_EMBEDDING_MODEL', ''),
    )


class ReceiptItemCategoryService:
    """Categorize receipt items: pinned, writing, then semantic match.

    A pinned mapping (:class:`ProductNameCategoryMapping`) always wins. If
    none exists, the category is picked from the owner's previously
    categorized products by database-side trigram similarity. If that also
    finds nothing, the owner's previously categorized products are compared
    by embedding-vector distance, to catch names that are written
    differently but mean the same thing. If none of the three stages find
    anything, the item falls back to the default category.
    """

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            embedding_provider: Provider used for the semantic-match stage.
                Defaults to a provider built from Django settings.
        """
        self._embedding_provider = (
            embedding_provider or build_embedding_provider()
        )

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

        semantic_match_category = self._semantic_match_category(
            user,
            product_name,
        )
        if semantic_match_category is not None:
            return semantic_match_category, ProductCategorySource.SEMANTIC_MATCH

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

    def _semantic_match_category(
        self,
        user: User,
        product_name: str,
    ) -> str | None:
        try:
            query_vector = self._embedding_provider.embed(product_name)
        except EmbeddingServiceError:
            logger.warning(
                'receipt_category_embedding_unavailable',
                exc_info=True,
            )
            return None

        self._backfill_missing_embeddings(user)

        threshold = settings.RECEIPT_CATEGORY_SEMANTIC_SIMILARITY_THRESHOLD
        max_distance = 1 - threshold
        match = (
            Product.objects.filter(user=user)
            .exclude(category__isnull=True)
            .exclude(name_embedding__isnull=True)
            .annotate(distance=CosineDistance('name_embedding', query_vector))
            .filter(distance__lte=max_distance)
            .select_related('category')
            .order_by('distance', '-created_at')
            .first()
        )
        return match.category.name if match and match.category else None

    def _backfill_missing_embeddings(self, user: User) -> None:
        """Compute and cache embeddings for candidates that lack one yet.

        A product's embedding is computed once and stored on the row, so
        later semantic-match lookups reuse it instead of recomputing it.
        """
        candidates = Product.objects.filter(
            user=user,
            name_embedding__isnull=True,
        ).exclude(category__isnull=True)[:_EMBEDDING_BACKFILL_BATCH_SIZE]

        for product in candidates:
            try:
                vector = self._embedding_provider.embed(product.product_name)
            except EmbeddingServiceError:
                logger.warning(
                    'receipt_category_embedding_unavailable',
                    exc_info=True,
                )
                return
            product.name_embedding = vector
            product.save(update_fields=['name_embedding'])


__all__ = [
    'ReceiptItemCategoryService',
    'build_embedding_provider',
    'normalize_product_name',
]
