"""Business operations for twin-category merge proposals."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from hasta_la_vista_money.receipts.models import (
    CategoryMergeProposalStatus,
    ProductCategory,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from hasta_la_vista_money.receipts.models import CategoryMergeProposal
    from hasta_la_vista_money.receipts.repositories.category_merge_proposal_repository import (  # noqa: E501
        CategoryMergeProposalRepository,
    )
    from hasta_la_vista_money.receipts.repositories.product_category_repository import (  # noqa: E501
        ProductCategoryRepository,
    )
    from hasta_la_vista_money.receipts.repositories.product_name_category_mapping_repository import (  # noqa: E501
        ProductNameCategoryMappingRepository,
    )
    from hasta_la_vista_money.receipts.repositories.product_repository import (
        ProductRepository,
    )
    from hasta_la_vista_money.users.models import User


class CategoryMergeProposalService:
    """Create, resolve and apply twin-category merge proposals."""

    def __init__(
        self,
        *,
        proposal_repository: CategoryMergeProposalRepository,
        product_category_repository: ProductCategoryRepository,
        product_repository: ProductRepository,
        mapping_repository: ProductNameCategoryMappingRepository,
    ) -> None:
        self.proposal_repository = proposal_repository
        self.product_category_repository = product_category_repository
        self.product_repository = product_repository
        self.mapping_repository = mapping_repository

    def create_if_absent(
        self,
        *,
        user: User,
        category_a: ProductCategory,
        category_b: ProductCategory,
    ) -> bool:
        """Create a pending proposal unless one already exists."""
        if category_a.pk == category_b.pk:
            return False
        if self.proposal_repository.exists_for_pair(
            user=user,
            category_a=category_a,
            category_b=category_b,
        ):
            return False
        self.proposal_repository.create(
            user=user,
            category_a=category_a,
            category_b=category_b,
        )
        return True

    def list_pending(self, *, user: User) -> QuerySet[CategoryMergeProposal]:
        """Return the user's pending proposals."""
        return self.proposal_repository.list_pending_for_user(user)

    @transaction.atomic
    def merge(self, *, user: User, proposal_id: int) -> ProductCategory | None:
        """Merge a proposal's redundant category into its survivor."""
        proposal = self.proposal_repository.get_for_user(
            user=user,
            proposal_id=proposal_id,
        )
        if (
            proposal is None
            or proposal.status != CategoryMergeProposalStatus.PENDING
            or proposal.category_a is None
            or proposal.category_b is None
        ):
            return None
        survivor, redundant = self._pick_survivor(
            user,
            proposal.category_a,
            proposal.category_b,
        )
        self.product_repository.move_category(
            user=user,
            from_category=redundant,
            to_category=survivor,
        )
        self.mapping_repository.repoint_category(
            user=user,
            from_category=redundant,
            to_category=survivor,
        )
        self.product_category_repository.delete(redundant)
        self.proposal_repository.resolve(
            proposal,
            CategoryMergeProposalStatus.MERGED,
        )
        return survivor

    def keep(self, *, user: User, proposal_id: int) -> bool:
        """Reject a proposal so the pair is never offered again."""
        proposal = self.proposal_repository.get_for_user(
            user=user,
            proposal_id=proposal_id,
        )
        if (
            proposal is None
            or proposal.status != CategoryMergeProposalStatus.PENDING
        ):
            return False
        self.proposal_repository.resolve(
            proposal,
            CategoryMergeProposalStatus.KEPT,
        )
        return True

    def _pick_survivor(
        self,
        user: User,
        category_a: ProductCategory,
        category_b: ProductCategory,
    ) -> tuple[ProductCategory, ProductCategory]:
        counts = self.product_repository.count_by_categories(
            user=user,
            categories=[category_a, category_b],
        )
        count_a = counts.get(category_a.pk, 0)
        count_b = counts.get(category_b.pk, 0)
        if count_a != count_b:
            return (
                (category_a, category_b)
                if count_a > count_b
                else (category_b, category_a)
            )
        if category_a.pk < category_b.pk:
            return category_a, category_b
        return category_b, category_a


__all__ = ['CategoryMergeProposalService']
