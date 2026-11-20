"""Invalidate coverage and retained balance checks after a money change.

The coverage service is injected: this module never builds a service or
looks an account up by id. Callers pass already-loaded accounts and either an
exact bank calendar day or ``None`` when the day is unknown. Category-only
edits must not call this module.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from hasta_la_vista_money.users.services.statement_balance_staleness import (
    mark_balance_checks_stale,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.finance_account.services.protocols import (
        AccountCoverageServiceProtocol,
    )
REASON_MOVEMENT_CHANGED = 'movement_changed'


def exact_bank_day(value: datetime | date | None) -> date | None:
    """Return only a proven bank calendar day, never a datetime date part.

    A stored datetime (including a technical UTC anchor) is not proof of the
    bank calendar day. Coverage then rechecks the whole corresponding period;
    the actual datetime still goes to ``moments`` for balance staleness,
    which converts it with the upload's explicit timezone.
    """
    if isinstance(value, datetime):
        return None
    return value


def note_financial_change(
    *,
    coverage_service: AccountCoverageServiceProtocol,
    changes: Sequence[tuple[Account, datetime | date | None]],
    moments: Iterable[datetime | date],
) -> None:
    """Recheck coverage per changed account and day, and stale balance checks.

    Coverage invalidation runs regardless of whether any verified balance
    upload exists; ``mark_balance_checks_stale`` simply finds none.
    """
    seen: set[tuple[int, date | None]] = set()
    for account, changed_at in changes:
        changed_on = exact_bank_day(changed_at)
        key = (account.pk, changed_on)
        if key in seen:
            continue
        seen.add(key)
        coverage_service.invalidate_for_movement_change(
            account=account,
            changed_on=changed_on,
            reason=REASON_MOVEMENT_CHANGED,
        )
    mark_balance_checks_stale(
        {account.pk for account, _ in changes},
        list(moments),
    )
