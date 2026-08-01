"""Protocol interfaces for user statistics services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from django.db.models import QuerySet

    from config.containers import ApplicationContainer
    from hasta_la_vista_money.transactions.models import Transaction
    from hasta_la_vista_money.users.models import (
        BankStatementRow,
        BankStatementUpload,
        User,
    )
    from hasta_la_vista_money.users.services import (
        bank_statement_reconciliation,
    )
    from hasta_la_vista_money.users.services.monthly_statistics_service import (
        DashboardSummaryStatisticsDict,
        StatisticsFilters,
    )
    from hasta_la_vista_money.users.services.statistics import UserStatistics
    from hasta_la_vista_money.users.services.summary_statistics_service import (
        UserDetailedStatisticsDict,
    )


@runtime_checkable
class UserStatisticsServiceProtocol(Protocol):
    """Protocol for cached profile statistics service."""

    def get_user_statistics(self, user: User) -> UserStatistics: ...

    def invalidate_cache(self, user: User) -> None: ...


@runtime_checkable
class DashboardSummaryStatisticsServiceProtocol(Protocol):
    """Callable protocol for dashboard summary statistics."""

    def __call__(
        self,
        user: User,
        container: ApplicationContainer,
    ) -> DashboardSummaryStatisticsDict: ...


@runtime_checkable
class UserDetailedStatisticsServiceProtocol(Protocol):
    """Callable protocol for detailed user statistics."""

    def __call__(
        self,
        user: User,
        container: ApplicationContainer,
        stats_filter: StatisticsFilters | None = None,
        page_number: int = 1,
        income_expense_page_number: int = 1,
        transfer_page_number: int = 1,
    ) -> UserDetailedStatisticsDict: ...


@runtime_checkable
class BankStatementReconciliationServiceProtocol(Protocol):
    """Protocol for statement reconciliation decisions."""

    def upload_history(
        self,
        user_id: int,
    ) -> QuerySet[BankStatementUpload]: ...

    def reconciliation_rows(
        self,
        upload: BankStatementUpload,
        outcome: str,
    ) -> QuerySet[BankStatementRow]: ...

    def decide(
        self,
        row_id: int,
        decision: str,
        user_id: int,
        candidate_id: int | None = None,
    ) -> BankStatementRow: ...

    def bulk_decide(
        self,
        row_ids: list[int],
        decision: str,
        user_id: int,
        upload_id: int,
    ) -> list[bank_statement_reconciliation.BulkDecisionResult]: ...

    def revise_linked_to_new(
        self,
        row_id: int,
        user_id: int,
    ) -> BankStatementRow: ...

    def current_candidates(
        self,
        row: BankStatementRow,
    ) -> QuerySet[Transaction]: ...

    def refresh_outcome_counts(self, upload: BankStatementUpload) -> None: ...


@runtime_checkable
class BankStatementRetentionServiceProtocol(Protocol):
    """Protocol for statement retention cleanup."""

    def cleanup_expired(self, now: datetime | None = None) -> int: ...
