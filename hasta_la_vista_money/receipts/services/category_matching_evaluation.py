"""Measure per-stage hit rate of product category matching.

Runs each of the three automatic stages (pinned name match, writing match,
semantic match) independently against the accumulated, already-categorized
product rows and reports what share of the cases where a stage produced a
candidate at all, that candidate's category was actually correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.postgres.search import TrigramSimilarity
from django.db.models.functions import Lower
from pgvector.django import CosineDistance

from core.services.embedding import EmbeddingServiceError
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategory,
    ProductNameCategoryMapping,
)
from hasta_la_vista_money.receipts.services.category_classifier import (
    build_embedding_provider,
    normalize_product_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from core.services.embedding import EmbeddingProvider
    from hasta_la_vista_money.users.models import User


@dataclass(frozen=True)
class StageEvaluationResult:
    """Hit-rate result for one categorization stage."""

    stage: str
    hits: int
    total: int

    @property
    def hit_rate(self) -> float:
        """Share of applicable cases the stage got right."""
        return self.hits / self.total if self.total else 0.0


@dataclass
class _StageTally:
    hits: int = 0
    total: int = 0

    def record(self, predicted: ProductCategory | None, actual: str) -> None:
        if predicted is None:
            return
        self.total += 1
        if predicted.name == actual:
            self.hits += 1


@dataclass
class _Tallies:
    pinned: _StageTally = field(default_factory=_StageTally)
    writing: _StageTally = field(default_factory=_StageTally)
    semantic: _StageTally = field(default_factory=_StageTally)

    def as_results(self) -> list[StageEvaluationResult]:
        return [
            StageEvaluationResult(
                'pinned_name_match',
                self.pinned.hits,
                self.pinned.total,
            ),
            StageEvaluationResult(
                'writing_match',
                self.writing.hits,
                self.writing.total,
            ),
            StageEvaluationResult(
                'semantic_match',
                self.semantic.hits,
                self.semantic.total,
            ),
        ]


def _pinned_candidate(
    product: Product,
    normalized_name: str,
) -> ProductCategory | None:
    mapping = (
        ProductNameCategoryMapping.objects.filter(
            user=product.user,
            normalized_product_name=normalized_name,
        )
        .select_related('category')
        .first()
    )
    return mapping.category if mapping else None


def _writing_candidate(
    product: Product,
    normalized_name: str,
) -> ProductCategory | None:
    threshold = settings.RECEIPT_CATEGORY_WRITING_SIMILARITY_THRESHOLD
    match = (
        Product.objects.filter(user=product.user)
        .exclude(pk=product.pk)
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
    return match.category if match else None


def _semantic_candidate(
    product: Product,
    provider: EmbeddingProvider,
) -> ProductCategory | None:
    try:
        query_vector = provider.embed(product.product_name)
    except EmbeddingServiceError:
        return None

    if product.name_embedding is None:
        product.name_embedding = query_vector
        product.save(update_fields=['name_embedding'])

    max_distance = 1 - settings.RECEIPT_CATEGORY_SEMANTIC_SIMILARITY_THRESHOLD
    match = (
        Product.objects.filter(user=product.user)
        .exclude(pk=product.pk)
        .exclude(category__isnull=True)
        .exclude(name_embedding__isnull=True)
        .annotate(distance=CosineDistance('name_embedding', query_vector))
        .filter(distance__lte=max_distance)
        .select_related('category')
        .order_by('distance', '-created_at')
        .first()
    )
    return match.category if match else None


def evaluate_category_matching_stages(
    *,
    users: Iterable[User] | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[StageEvaluationResult]:
    """Evaluate pinned/writing/semantic match hit rate on accumulated data.

    For every already-categorized product row, each stage is asked to find
    a category among the owner's *other* products, independently of the
    other stages. ``total`` for a stage only counts rows where that stage
    produced a candidate at all (rows it would skip do not count against
    it); ``hits`` counts how many of those candidates matched the row's
    actual category.

    Args:
        users: Restrict evaluation to these users. Defaults to all users
            with categorized products.
        embedding_provider: Provider for the semantic stage. Defaults to
            the provider built from Django settings.

    Returns:
        One :class:`StageEvaluationResult` per stage.
    """
    provider = embedding_provider or build_embedding_provider()
    products_qs = Product.objects.exclude(category__isnull=True).select_related(
        'user',
        'category',
    )
    if users is not None:
        products_qs = products_qs.filter(user__in=users)

    tallies = _Tallies()
    for product in products_qs.iterator():
        normalized_name = normalize_product_name(product.product_name)
        if not normalized_name or product.category is None:
            continue
        actual_category = product.category.name

        tallies.pinned.record(
            _pinned_candidate(product, normalized_name),
            actual_category,
        )
        tallies.writing.record(
            _writing_candidate(product, normalized_name),
            actual_category,
        )
        tallies.semantic.record(
            _semantic_candidate(product, provider),
            actual_category,
        )

    return tallies.as_results()


__all__ = [
    'StageEvaluationResult',
    'evaluate_category_matching_stages',
]
