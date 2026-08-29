"""Django repository for twin-category merge proposals."""

from django.db.models import QuerySet
from django.utils import timezone

from hasta_la_vista_money.receipts.models import (
    CategoryMergeProposal,
    CategoryMergeProposalStatus,
    ProductCategory,
)
from hasta_la_vista_money.users.models import User


class CategoryMergeProposalRepository:
    """Persist and query twin-category merge proposals."""

    def list_pending_for_user(
        self,
        user: User,
    ) -> QuerySet[CategoryMergeProposal]:
        """Return the user's pending proposals with related categories."""
        return (
            CategoryMergeProposal.objects.filter(
                user=user,
                status=CategoryMergeProposalStatus.PENDING,
            )
            .select_related('category_a', 'category_b')
            .order_by('-created_at')
        )

    def get_for_user(
        self,
        *,
        user: User,
        proposal_id: int,
    ) -> CategoryMergeProposal | None:
        """Return a user's proposal by id, if it exists."""
        return CategoryMergeProposal.objects.filter(
            pk=proposal_id,
            user=user,
        ).first()

    def exists_for_pair(
        self,
        *,
        user: User,
        category_a: ProductCategory,
        category_b: ProductCategory,
    ) -> bool:
        """Return whether a proposal already exists for the pair."""
        first, second = (category_a, category_b)
        if first.pk > second.pk:
            first, second = second, first
        return CategoryMergeProposal.objects.filter(
            user=user,
            category_a=first,
            category_b=second,
        ).exists()

    def create(
        self,
        *,
        user: User,
        category_a: ProductCategory,
        category_b: ProductCategory,
    ) -> CategoryMergeProposal:
        """Create a pending proposal with the pair ordered by primary key."""
        first, second = (category_a, category_b)
        if first.pk > second.pk:
            first, second = second, first
        return CategoryMergeProposal.objects.create(
            user=user,
            category_a=first,
            category_b=second,
        )

    def resolve(
        self,
        proposal: CategoryMergeProposal,
        status: CategoryMergeProposalStatus,
    ) -> None:
        """Move a proposal to a terminal status."""
        CategoryMergeProposal.objects.filter(pk=proposal.pk).update(
            status=status,
            resolved_at=timezone.now(),
        )
