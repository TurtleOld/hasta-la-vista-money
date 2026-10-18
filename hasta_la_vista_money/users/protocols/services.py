"""Protocol interfaces for user statistics services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from decimal import Decimal

    from django.db.models import QuerySet

    from config.containers import ApplicationContainer
    from hasta_la_vista_money.finance_account.models import (
        Account,
        TransferMoneyLog,
    )
    from hasta_la_vista_money.transactions.models import Category, Transaction
    from hasta_la_vista_money.users.models import (
        BankStatementRow,
        BankStatementUpload,
        User,
    )
    from hasta_la_vista_money.users.services import (
        bank_statement_reconciliation,
    )
    from hasta_la_vista_money.users.services.bank_statement_import import (
        StatementImportResult,
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

    def get_user_statistics(
        self,
        user: User,
        currency: str,
    ) -> UserStatistics: ...

    def invalidate_cache(self, user: User, currency: str) -> None: ...


@runtime_checkable
class DashboardSummaryStatisticsServiceProtocol(Protocol):
    """Callable protocol for dashboard summary statistics."""

    def __call__(
        self,
        user: User,
        currency: str,
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
class StatementMarkupServiceProtocol(Protocol):
    """Protocol for posting RosDorBank rows after user markup."""

    def pending_rows(
        self,
        upload: BankStatementUpload,
    ) -> QuerySet[BankStatementRow]: ...

    def categories(
        self,
        user: User,
        transaction_type: str,
    ) -> list[Category]: ...

    def post(
        self,
        row_id: int,
        user_id: int,
        category_id: int | None,
    ) -> BankStatementRow: ...

    def post_transfer(
        self,
        row_id: int,
        user_id: int,
        account_id: int | None,
    ) -> BankStatementRow: ...

    def skip(self, row_id: int, user_id: int) -> BankStatementRow: ...


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

    def mark_not_payment(
        self,
        row_id: int,
        user_id: int,
    ) -> BankStatementRow: ...

    def pending_transfer_rows(
        self,
        account: Account,
    ) -> QuerySet[BankStatementRow]: ...

    def pending_transfers_for_user(
        self,
        user: User,
    ) -> QuerySet[BankStatementRow]: ...

    def current_candidates(
        self,
        row: BankStatementRow,
    ) -> QuerySet[Transaction]: ...

    def refresh_outcome_counts(self, upload: BankStatementUpload) -> None: ...


@runtime_checkable
class StatementRowLinkServiceProtocol(Protocol):
    """Statement rows closed by movements; credit-card repayment rows."""

    def has_linked_row(
        self,
        movement: Transaction | TransferMoneyLog,
    ) -> bool: ...

    def release_linked_rows(
        self,
        movement: Transaction | TransferMoneyLog,
    ) -> None: ...

    def lock_repayment_row(
        self,
        row_id: int,
        *,
        to_account: Account,
        amount: Decimal,
    ) -> BankStatementRow: ...

    def close_repayment_row(
        self,
        row: BankStatementRow,
        transfer: TransferMoneyLog,
    ) -> None: ...

    def repayment_candidates(
        self,
        rows: Sequence[BankStatementRow],
    ) -> dict[int, list[TransferMoneyLog]]: ...

    def link_repayment(
        self,
        row_id: int,
        transfer_id: int,
        user_id: int,
    ) -> BankStatementRow: ...


@runtime_checkable
class BankStatementRetentionServiceProtocol(Protocol):
    """Protocol for statement retention cleanup."""

    def cleanup_expired(self, now: datetime | None = None) -> int: ...


@runtime_checkable
class BankStatementImportServiceProtocol(Protocol):
    """Protocol for the unified bank statement import pipeline."""

    def restart_if_stale(self, upload: BankStatementUpload) -> bool: ...

    def import_statement(
        self,
        upload: BankStatementUpload,
    ) -> StatementImportResult: ...
