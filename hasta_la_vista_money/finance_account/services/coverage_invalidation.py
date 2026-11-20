"""Cross-domain hooks that invalidate coverage after real changes.

These helpers are deliberately side-effect commands over existing
confirmations. They never create or confirm coverage, never change money and
never delete a confirmation. A caller that only changes a category must not
call them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.repositories.account_coverage_repository import (  # noqa: E501
    AccountCoverageRepository,
)
from hasta_la_vista_money.finance_account.services.coverage_service import (
    AccountCoverageService,
)

if TYPE_CHECKING:
    from datetime import date

    from hasta_la_vista_money.users.models import (
        BankStatementRow,
        BankStatementUpload,
    )


def _service() -> AccountCoverageService:
    return AccountCoverageService(repository=AccountCoverageRepository())


def invalidate_coverage_for_row_problem(
    row: BankStatementRow,
    *,
    reason: str,
) -> int:
    """Recheck a row's exact bank day, or its whole period if unknown."""
    return _service().invalidate_for_row_problem(row=row, reason=reason)


def invalidate_coverage_for_upload_problem(
    upload: BankStatementUpload,
    *,
    reason: str,
) -> int:
    """Recheck an imported document's period, or the whole period if unknown."""
    return _service().invalidate_for_upload_problem(
        upload=upload,
        reason=reason,
    )


def invalidate_coverage_for_movement_change(
    account_id: int,
    *,
    changed_on: date | None,
    reason: str = 'movement_changed',
) -> int:
    """Recheck changed bank day; callers pass ``None`` when it is unknown.

    Ticket 09 financial writers own deciding whether an edit changes money or
    dates. A category-only edit must not call this helper.
    """
    account = Account.objects.get(pk=account_id)
    return _service().invalidate_for_movement_change(
        account=account,
        changed_on=changed_on,
        reason=reason,
    )


def invalidate_coverage_for_account_life_change(
    account: Account,
    *,
    previous_opened_on: date | None,
    previous_closed_on: date | None,
    reason: str = 'account_life_changed',
) -> int:
    """Recheck moved account life boundaries.

    Known old and new boundaries produce exact windows. If either side was
    unknown, the whole corresponding period is rechecked rather than inventing
    a range.
    """
    return _service().invalidate_for_account_life_change(
        account=account,
        previous_opened_on=previous_opened_on,
        previous_closed_on=previous_closed_on,
        reason=reason,
    )
