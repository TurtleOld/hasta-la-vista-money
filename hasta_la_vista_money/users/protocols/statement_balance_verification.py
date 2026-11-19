"""Protocol for historical bank balance verification."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from datetime import date, datetime

    from hasta_la_vista_money.users.services.statement_balance_verification import (  # noqa: E501
        BalanceVerificationResult,
        FinalReconciliationBlock,
    )


@runtime_checkable
class StatementBalanceVerificationServiceProtocol(Protocol):
    """Compare a bank balance with the account balance at its moment."""

    def verification(
        self,
        upload_id: int,
        user_id: int,
    ) -> BalanceVerificationResult:
        """Return the last result with its freshness, without recalculating."""
        ...

    def verify(
        self,
        upload_id: int,
        user_id: int,
    ) -> BalanceVerificationResult:
        """Recalculate at the stored moment and persist the last result."""
        ...

    def confirm_balance_snapshot(
        self,
        upload_id: int,
        user_id: int,
        *,
        balance_kind: str,
        balance_date: date | None = None,
        balance_at: datetime | None = None,
        timezone_name: str = '',
    ) -> BalanceVerificationResult:
        """Store the document- or owner-confirmed balance moment and kind."""
        ...

    def explain_mismatch(
        self,
        upload_id: int,
        user_id: int,
        *,
        reason: str,
    ) -> BalanceVerificationResult:
        """Clear the unexplained flag with an owner reason and audit."""
        ...

    def final_reconciliation_block(
        self,
        *,
        user_id: int,
        account_ids: Collection[int] | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> FinalReconciliationBlock | None:
        """Return the retained mismatch block or ``None``."""
        ...

    def mark_movements_changed(
        self,
        account_ids: Collection[int],
        moments: Iterable[datetime],
    ) -> int:
        """Require a new check after an influencing movement change."""
        ...
