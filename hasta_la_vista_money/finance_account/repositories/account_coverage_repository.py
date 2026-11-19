"""Repository for owner-confirmed statement coverage periods."""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import (
    AccountCoverageConfirmation,
)


class AccountCoverageRepository:
    """Data access for coverage confirmations of one account."""

    def for_account(
        self,
        account_id: int,
        *,
        active_only: bool = False,
        for_update: bool = False,
    ) -> QuerySet[AccountCoverageConfirmation]:
        queryset = AccountCoverageConfirmation.objects.filter(
            account_id=account_id,
        )
        if active_only:
            queryset = queryset.filter(needs_recheck=False)
        if for_update:
            queryset = queryset.select_for_update()
        return queryset.order_by('period_start', 'pk')

    def overlapping(
        self,
        account_id: int,
        period_start: date,
        period_end: date,
        *,
        active_only: bool = True,
        for_update: bool = False,
    ) -> QuerySet[AccountCoverageConfirmation]:
        return self.for_account(
            account_id,
            active_only=active_only,
            for_update=for_update,
        ).filter(
            period_start__lte=period_end,
            period_end__gte=period_start,
        )

    def create(
        self,
        **kwargs: object,
    ) -> AccountCoverageConfirmation:
        return AccountCoverageConfirmation.objects.create(**kwargs)
