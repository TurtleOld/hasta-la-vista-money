"""Explicit coverage of account periods and its interval arithmetic.

Coverage is an owner assertion about inclusive calendar dates. It is not a
proof that a statement was processed and it never changes money. Interval
union and gaps live here, next to the confirmations they describe, rather
than in a separate interval engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    AccountCoverageConfirmation,
)
from hasta_la_vista_money.system.services.audit_context import audit_operation

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.finance_account.repositories.account_coverage_repository import (  # noqa: E501
        AccountCoverageRepository,
    )
    from hasta_la_vista_money.users.models import (
        BankStatementUpload,
        User,
    )

ONE_DAY = timedelta(days=1)


@dataclass(frozen=True, kw_only=True)
class DateWindow:
    """Inclusive calendar date bounds."""

    start: date
    end: date


@dataclass(frozen=True, kw_only=True)
class CoverageInterval:
    """One current coverage interval, already clipped and merged."""

    start: date
    end: date
    source: str
    confirmation_id: int | None = None
    statement_upload_id: int | None = None
    confirmed_at: object | None = None
    recheck_reason: str = ''


@dataclass(frozen=True, kw_only=True)
class CoverageSummary:
    """Coverage of one account inside the requested period."""

    period_start: date
    period_end: date
    applicable_period: DateWindow | None
    intervals: tuple[CoverageInterval, ...]
    gaps: tuple[DateWindow, ...]
    invalidated: tuple[CoverageInterval, ...]
    fully_covered: bool


def _clip(
    start: date,
    end: date,
    *,
    opened_on: date | None,
    closed_on: date | None,
) -> DateWindow | None:
    if opened_on is not None:
        start = max(start, opened_on)
    if closed_on is not None:
        end = min(end, closed_on)
    if start > end:
        return None
    return DateWindow(start=start, end=end)


def _merge_windows(
    windows: list[DateWindow],
) -> list[DateWindow]:
    if not windows:
        return []
    ordered = sorted(windows, key=lambda window: (window.start, window.end))
    merged = [ordered[0]]
    for window in ordered[1:]:
        current = merged[-1]
        if window.start <= current.end + ONE_DAY:
            merged[-1] = DateWindow(
                start=current.start,
                end=max(current.end, window.end),
            )
        else:
            merged.append(window)
    return merged


def _gap_windows(
    period_start: date,
    period_end: date,
    covered: list[DateWindow],
) -> tuple[DateWindow, ...]:
    gaps: list[DateWindow] = []
    cursor = period_start
    for window in covered:
        if window.start > cursor:
            gaps.append(
                DateWindow(
                    start=cursor,
                    end=window.start - ONE_DAY,
                ),
            )
        cursor = max(cursor, window.end + ONE_DAY)
    if cursor <= period_end:
        gaps.append(DateWindow(start=cursor, end=period_end))
    return tuple(gaps)


class AccountCoverageService:
    """Confirm, merge and invalidate coverage for an owner's accounts."""

    def __init__(
        self,
        repository: AccountCoverageRepository,
    ) -> None:
        self.repository = repository

    def confirm(
        self,
        *,
        owner: User,
        account: Account,
        period_start: date,
        period_end: date,
        source: str,
        statement_upload: BankStatementUpload | None = None,
    ) -> AccountCoverageConfirmation:
        if account.user_id != owner.pk:
            raise PermissionDenied(_('Счёт принадлежит другому пользователю'))
        if source not in AccountCoverageConfirmation.Source.values:
            raise ValidationError(_('Неизвестный источник покрытия'))
        if (
            source == AccountCoverageConfirmation.Source.MANUAL
            and account.type_account != constants.ACCOUNT_TYPE_CASH
        ):
            raise ValidationError(
                _('Ручное покрытие доступно только для наличных'),
            )
        if period_start > period_end:
            raise ValidationError(
                _('Начало периода не может быть позже конца'),
            )
        if statement_upload is not None:
            if statement_upload.user_id != owner.pk:
                raise PermissionDenied(
                    _('Выписка принадлежит другому пользователю'),
                )
            if statement_upload.account_id != account.pk:
                raise ValidationError(
                    _('Выписка относится к другому счёту'),
                )
            if source == AccountCoverageConfirmation.Source.MANUAL:
                raise ValidationError(
                    _('Ручное покрытие не ссылается на выписку'),
                )

        with transaction.atomic(), audit_operation():
            return self.repository.create(
                account=account,
                period_start=period_start,
                period_end=period_end,
                source=source,
                statement_upload=statement_upload,
                confirmed_by=owner,
            )

    def summary(
        self,
        *,
        account: Account,
        period_start: date,
        period_end: date,
    ) -> CoverageSummary:
        if period_start > period_end:
            raise ValidationError(
                _('Начало периода не может быть позже конца'),
            )
        applicable = _clip(
            period_start,
            period_end,
            opened_on=account.opened_on,
            closed_on=account.closed_on,
        )
        active = list(
            self.repository.overlapping(
                account.pk,
                period_start,
                period_end,
                active_only=True,
            ),
        )
        invalidated = list(
            self.repository.overlapping(
                account.pk,
                period_start,
                period_end,
                active_only=False,
            ).filter(needs_recheck=True),
        )
        invalidated_intervals = tuple(
            CoverageInterval(
                start=max(item.period_start, period_start),
                end=min(item.period_end, period_end),
                source=item.source,
                confirmation_id=item.pk,
                statement_upload_id=item.statement_upload_id,
                confirmed_at=item.confirmed_at,
                recheck_reason=item.recheck_reason,
            )
            for item in invalidated
        )
        if applicable is None:
            return CoverageSummary(
                period_start=period_start,
                period_end=period_end,
                applicable_period=None,
                intervals=(),
                gaps=(),
                invalidated=invalidated_intervals,
                fully_covered=False,
            )

        windows = [
            window
            for item in active
            if (
                window := _clip(
                    max(item.period_start, applicable.start),
                    min(item.period_end, applicable.end),
                    opened_on=applicable.start,
                    closed_on=applicable.end,
                )
            )
            is not None
        ]
        merged = _merge_windows(windows)
        gaps = _gap_windows(applicable.start, applicable.end, merged)
        intervals = tuple(
            self._interval_for_window(
                window,
                active=active,
                windows=windows,
            )
            for window in merged
        )
        return CoverageSummary(
            period_start=period_start,
            period_end=period_end,
            applicable_period=applicable,
            intervals=intervals,
            gaps=gaps,
            invalidated=invalidated_intervals,
            fully_covered=not gaps,
        )

    def invalidate(
        self,
        *,
        owner: User,
        account: Account,
        affected_start: date | None,
        affected_end: date | None,
        reason: str,
    ) -> list[AccountCoverageConfirmation]:
        """Recheck the exact affected part, or the whole period if unknown."""
        if account.user_id != owner.pk:
            raise PermissionDenied(_('Счёт принадлежит другому пользователю'))
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise ValidationError(_('Нужна причина повторной проверки'))
        if (
            affected_start is not None
            and affected_end is not None
            and affected_start > affected_end
        ):
            raise ValidationError(
                _('Начало интервала не может быть позже конца'),
            )

        with transaction.atomic(), audit_operation():
            if affected_start is None or affected_end is None:
                confirmations = list(
                    self.repository.for_account(
                        account.pk,
                        active_only=True,
                        for_update=True,
                    ),
                )
            else:
                confirmations = list(
                    self.repository.overlapping(
                        account.pk,
                        affected_start,
                        affected_end,
                        active_only=True,
                        for_update=True,
                    ),
                )

            return [
                confirmation
                for confirmation in confirmations
                if self._invalidate_one(
                    confirmation,
                    account=account,
                    affected_start=affected_start,
                    affected_end=affected_end,
                    reason=cleaned_reason,
                )
            ]

    def _invalidate_one(
        self,
        confirmation: AccountCoverageConfirmation,
        *,
        account: Account,
        affected_start: date | None,
        affected_end: date | None,
        reason: str,
    ) -> bool:
        if affected_start is None or affected_end is None:
            self._mark_recheck(confirmation, reason)
            return True

        overlap_start = max(confirmation.period_start, affected_start)
        overlap_end = min(confirmation.period_end, affected_end)
        if overlap_start > overlap_end:
            return False
        if (
            overlap_start == confirmation.period_start
            and overlap_end == confirmation.period_end
        ):
            self._mark_recheck(confirmation, reason)
            return True

        self._split_and_mark(
            confirmation,
            account=account,
            overlap_start=overlap_start,
            overlap_end=overlap_end,
            reason=reason,
        )
        return True

    def _split_and_mark(
        self,
        confirmation: AccountCoverageConfirmation,
        *,
        account: Account,
        overlap_start: date,
        overlap_end: date,
        reason: str,
    ) -> None:
        if confirmation.period_start < overlap_start:
            self.repository.create(
                account=account,
                period_start=confirmation.period_start,
                period_end=overlap_start - ONE_DAY,
                source=confirmation.source,
                statement_upload=confirmation.statement_upload,
                confirmed_by=confirmation.confirmed_by,
            )
        if overlap_end < confirmation.period_end:
            self.repository.create(
                account=account,
                period_start=overlap_end + ONE_DAY,
                period_end=confirmation.period_end,
                source=confirmation.source,
                statement_upload=confirmation.statement_upload,
                confirmed_by=confirmation.confirmed_by,
            )
        confirmation.period_start = overlap_start
        confirmation.period_end = overlap_end
        self._mark_recheck(confirmation, reason)

    @staticmethod
    def _interval_for_window(
        merged: DateWindow,
        *,
        active: list[AccountCoverageConfirmation],
        windows: list[DateWindow],
    ) -> CoverageInterval:
        for confirmation, window in zip(active, windows, strict=False):
            if window.start <= merged.end and window.end >= merged.start:
                return CoverageInterval(
                    start=merged.start,
                    end=merged.end,
                    source=confirmation.source,
                    confirmation_id=confirmation.pk,
                    statement_upload_id=confirmation.statement_upload_id,
                    confirmed_at=confirmation.confirmed_at,
                )
        raise ValidationError(_('Не удалось определить источник покрытия'))

    @staticmethod
    def _mark_recheck(
        confirmation: AccountCoverageConfirmation,
        reason: str,
    ) -> None:
        confirmation.needs_recheck = True
        confirmation.recheck_reason = reason
        confirmation.save(
            update_fields=[
                'period_start',
                'period_end',
                'needs_recheck',
                'recheck_reason',
            ],
        )
