"""Invalidate retained historical balance checks after movement changes."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

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

    Only a change at or after the verified bank moment can change the
    reconstructed balance. A category-only edit carries the same date and
    amount and therefore never reaches this hook with an influencing change.
    """
    changed_moments = list(moments)
    if not account_ids or not changed_moments:
        return 0
    changed_days = [
        timezone.localtime(moment).date()
        if isinstance(moment, datetime)
        else moment
        for moment in changed_moments
    ]
    stale_ids = [
        upload.pk
        for upload in StatementBalanceVerificationRepository.verifiable_uploads(
            account_ids,
        )
        if _is_influenced(upload, changed_moments, changed_days)
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
    changed_days: list[date],
) -> bool:
    if upload.retention_cleaned_at is not None:
        return False
    if upload.statement_balance_at is not None:
        return _has_instant_after(upload, changed_moments)
    balance_day = upload.statement_balance_date
    if balance_day is None:
        return False
    if upload.statement_balance_kind == BankStatementUpload.BalanceKind.OPENING:
        return any(day < balance_day for day in changed_days)
    return any(day >= balance_day for day in changed_days)


def _has_instant_after(
    upload: BankStatementUpload,
    changed_moments: list[datetime | date],
) -> bool:
    balance_at = upload.statement_balance_at
    if balance_at is None:
        return False
    balance_day = timezone.localtime(balance_at).date()
    for moment in changed_moments:
        if isinstance(moment, datetime):
            if moment >= balance_at:
                return True
        elif moment >= balance_day:
            return True
    return False
