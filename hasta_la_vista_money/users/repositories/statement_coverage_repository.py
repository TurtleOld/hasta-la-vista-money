"""ORM access for confirmed statement periods."""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import (
    StatementPeriodCoverage,
)
from hasta_la_vista_money.users.models import (
    BankStatementUpload,
    User,
)


class StatementCoverageRepository:
    """Read and record statement period coverage records."""

    @staticmethod
    def for_account(
        account_id: int,
        period_start: date,
        period_end: date,
    ) -> QuerySet[StatementPeriodCoverage]:
        """Return coverage overlapping the selected period."""
        return (
            StatementPeriodCoverage.objects.filter(
                account_id=account_id,
                period_start__lte=period_end,
                period_end__gte=period_start,
            )
            .select_related('upload', 'author')
            .order_by('period_start', 'pk')
        )

    def record(
        self,
        *,
        account_id: int,
        period_start: date,
        period_end: date,
        source: str,
        author: User | None,
        upload: BankStatementUpload | None = None,
    ) -> StatementPeriodCoverage:
        """Create or reuse a coverage record for the same bounds."""
        coverage, _ = StatementPeriodCoverage.objects.get_or_create(
            account_id=account_id,
            upload=upload,
            source=source,
            period_start=period_start,
            period_end=period_end,
            defaults={'author': author},
        )
        return coverage
