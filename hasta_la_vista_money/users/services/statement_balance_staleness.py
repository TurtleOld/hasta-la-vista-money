"""Invalidate retained historical balance checks after movement changes."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from hasta_la_vista_money.users.models import BankStatementUpload
from hasta_la_vista_money.users.repositories.statement_balance_verification_repository import (  # noqa: E501
    StatementBalanceVerificationRepository,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

REASON_MOVEMENT_CHANGED = 'movement_changed'


def mark_balance_checks_stale(
    account_ids: Collection[int],
    moments: Iterable[datetime | date],
) -> int:
    """Mark retained balance checks for accounts as needing a new check.

    ``balance_at`` reconstructs the past as the current balance minus events
    strictly after the moment. A known financial change **at or before** the
    moment therefore changes the check; a change strictly after it cancels
    out and leaves the check fresh.

    A ``date`` argument is a bank day (for example ``bank_calendar_date``);
    a ``datetime`` is converted to the upload's explicitly supplied balance
    timezone. Unknown bounds are treated conservatively as influencing.
    Retention does not exempt a check: the retained metadata still needs a
    new check and the bank sums stay deleted.
    """
    changed_moments = list(moments)
    if not account_ids or not changed_moments:
        return 0
    stale_ids = [
        upload.pk
        for upload in StatementBalanceVerificationRepository.verifiable_uploads(
            account_ids,
        )
        if _is_influenced(upload, changed_moments)
    ]
    if not stale_ids:
        return 0
    BankStatementUpload.objects.filter(pk__in=stale_ids).update(
        balance_needs_recheck=True,
        balance_stale_reason=REASON_MOVEMENT_CHANGED,
    )
    return len(stale_ids)


def _is_influenced(
    upload: BankStatementUpload,
    changed_moments: list[datetime | date],
) -> bool:
    if upload.statement_balance_at is not None:
        return _instant_influenced(upload, changed_moments)
    balance_day = upload.statement_balance_date
    if balance_day is None:
        return False
    if upload.statement_balance_kind == BankStatementUpload.BalanceKind.UNKNOWN:
        return True
    opening = (
        upload.statement_balance_kind == BankStatementUpload.BalanceKind.OPENING
    )
    zone = _zone(upload.statement_balance_timezone)
    changed_days = [_bank_day(moment, zone) for moment in changed_moments]
    if any(day is None for day in changed_days):
        return True
    if opening:
        return any(day < balance_day for day in changed_days if day is not None)
    return any(day <= balance_day for day in changed_days if day is not None)


def _instant_influenced(
    upload: BankStatementUpload,
    changed_moments: list[datetime | date],
) -> bool:
    balance_at = upload.statement_balance_at
    if balance_at is None:
        return False
    bank_day = _instant_bank_day(upload, balance_at)
    for moment in changed_moments:
        if isinstance(moment, datetime):
            if timezone.is_naive(moment):
                return True
            if moment <= balance_at:
                return True
        elif moment <= bank_day:
            return True
    return False


def _instant_bank_day(
    upload: BankStatementUpload,
    balance_at: datetime,
) -> date:
    if upload.statement_balance_date is not None:
        return upload.statement_balance_date
    zone = _zone(upload.statement_balance_timezone)
    if zone is not None:
        return balance_at.astimezone(zone).date()
    return balance_at.date()


def _bank_day(
    moment: datetime | date,
    zone: ZoneInfo | None,
) -> date | None:
    """Return the bank day of a change, or ``None`` when it is unknown."""
    if not isinstance(moment, datetime):
        return moment
    if timezone.is_naive(moment) or zone is None:
        return None
    return moment.astimezone(zone).date()


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
