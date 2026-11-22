"""Independent statement period coverage and its gaps."""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext as _

from hasta_la_vista_money.finance_account.models import (
    StatementPeriodCoverage,
)
from hasta_la_vista_money.users.models import BankStatementUpload, User
from hasta_la_vista_money.users.repositories.statement_coverage_repository import (  # noqa: E501
    StatementCoverageRepository,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import Account

COVERED_STATE = 'covered'
PARTIAL_STATE = 'partial'
UNKNOWN_STATE = 'unknown'


@dataclass(frozen=True)
class CoverageInterval:
    """One confirmed coverage interval clipped to the selected period."""

    period_start: date
    period_end: date
    source: str
    source_label: str
    upload: BankStatementUpload | None
    author: User | None
    has_no_rows: bool


@dataclass(frozen=True)
class CoverageGap:
    """An uncovered interval inside the selected period."""

    period_start: date
    period_end: date


@dataclass(frozen=True)
class CoverageSummary:
    """Coverage of one account period, independent of rows and balance."""

    state: str
    state_label: str
    intervals: tuple[CoverageInterval, ...]
    gaps: tuple[CoverageGap, ...]


class StatementCoverageService:
    """Record and summarise independent period coverage."""

    def __init__(
        self,
        coverage_repository: StatementCoverageRepository,
    ) -> None:
        """Initialise the service with its coverage repository.

        Args:
            coverage_repository: Repository for coverage records.
        """
        self._coverage_repository = coverage_repository

    def record_statement_period(
        self,
        upload: BankStatementUpload,
        period_start: date | None,
        period_end: date | None,
    ) -> StatementPeriodCoverage | None:
        """Record the explicit period of a parsed statement.

        A reparse without usable bounds retires this upload's previous
        confirmation instead of leaving a stale interval actual.

        Args:
            upload: Parsed statement upload.
            period_start: Explicit statement start, if the parser found one.
            period_end: Explicit statement end, if the parser found one.

        Returns:
            The recorded coverage, or ``None`` when the period is unusable.
        """
        if (
            period_start is None
            or period_end is None
            or period_end < period_start
        ):
            self._coverage_repository.retire_without_bounds(upload)
            return None
        return self._coverage_repository.record(
            account_id=upload.account_id,
            period_start=period_start,
            period_end=period_end,
            source=StatementPeriodCoverage.Source.BANK_STATEMENT,
            author=upload.user,
            upload=upload,
        )

    def confirm_manual(
        self,
        user: User,
        account: 'Account',
        period_start: date,
        period_end: date,
    ) -> StatementPeriodCoverage:
        """Confirm coverage by the account owner.

        Manual confirmation is not a bank statement and never resolves
        statement rows.

        Args:
            user: Owner confirming the period.
            account: Account whose period is confirmed.
            period_start: First covered day.
            period_end: Last covered day.

        Returns:
            The recorded manual coverage.

        Raises:
            PermissionDenied: If the user does not own the account.
            ValidationError: If the period is reversed.
        """
        if account.user_id != user.pk:
            raise PermissionDenied(_('Покрытие подтверждает только владелец.'))
        if period_end < period_start:
            raise ValidationError(_('Конец периода раньше начала.'))
        return self._coverage_repository.record(
            account_id=account.pk,
            period_start=period_start,
            period_end=period_end,
            source=StatementPeriodCoverage.Source.MANUAL_CONFIRMATION,
            author=user,
        )

    def summary(
        self,
        account: 'Account',
        period_start: date,
        period_end: date,
    ) -> CoverageSummary:
        """Build coverage intervals and gaps for the selected period.

        Args:
            account: Account to summarise.
            period_start: First day of the selected period.
            period_end: Last day of the selected period.

        Returns:
            Coverage state, intervals and gaps.
        """
        intervals = tuple(
            self._interval(coverage, period_start, period_end)
            for coverage in self._coverage_repository.for_account(
                account.pk,
                period_start,
                period_end,
            )
        )
        gaps = self._gaps(intervals, period_start, period_end)
        if not intervals:
            state = UNKNOWN_STATE
            label = _('Неизвестен — требуется ручное подтверждение')
        elif gaps:
            state = PARTIAL_STATE
            label = _('Покрыт частично — есть разрывы')
        else:
            state = COVERED_STATE
            label = _('Покрыт')
        return CoverageSummary(
            state=state,
            state_label=str(label),
            intervals=intervals,
            gaps=gaps,
        )

    @staticmethod
    def _interval(
        coverage: StatementPeriodCoverage,
        period_start: date,
        period_end: date,
    ) -> CoverageInterval:
        """Clip one coverage record to the selected period."""
        start = max(coverage.period_start, period_start)
        end = min(coverage.period_end, period_end)
        has_no_rows = (
            coverage.source == StatementPeriodCoverage.Source.BANK_STATEMENT
            and coverage.upload is not None
            and coverage.upload.total_transactions == 0
        )
        return CoverageInterval(
            period_start=start,
            period_end=end,
            source=coverage.source,
            source_label=str(coverage.get_source_display()),
            upload=coverage.upload,
            author=coverage.author,
            has_no_rows=has_no_rows,
        )

    @staticmethod
    def _gaps(
        intervals: tuple[CoverageInterval, ...],
        period_start: date,
        period_end: date,
    ) -> tuple[CoverageGap, ...]:
        """Return uncovered intervals inside the selected period."""
        if not intervals:
            return ()
        merged: list[tuple[date, date]] = []
        for interval in sorted(intervals, key=lambda item: item.period_start):
            if not merged:
                merged.append((interval.period_start, interval.period_end))
                continue
            last_start, last_end = merged[-1]
            if interval.period_start.toordinal() > last_end.toordinal() + 1:
                merged.append((interval.period_start, interval.period_end))
            else:
                merged[-1] = (
                    last_start,
                    max(last_end, interval.period_end),
                )
        gaps: list[CoverageGap] = []
        cursor = period_start.toordinal()
        for start, end in merged:
            if start.toordinal() > cursor:
                gaps.append(
                    CoverageGap(
                        period_start=date.fromordinal(cursor),
                        period_end=date.fromordinal(start.toordinal() - 1),
                    ),
                )
            if end >= period_end:
                return tuple(gaps)
            cursor = max(cursor, end.toordinal() + 1)
        if cursor <= period_end.toordinal():
            gaps.append(
                CoverageGap(
                    period_start=date.fromordinal(cursor),
                    period_end=period_end,
                ),
            )
        return tuple(gaps)
