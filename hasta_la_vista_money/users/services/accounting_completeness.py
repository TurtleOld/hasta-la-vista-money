"""Independent completeness assessment for selected accounts and period.

Coverage, statement processing and balance verification are independent
characteristics. This service only reads existing records; it never posts a
movement or rewrites an import outcome.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.core.calendar_days import local_calendar_date
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.finance_account.services.coverage_service import (
        CoverageSummary,
        DateWindow,
    )
    from hasta_la_vista_money.finance_account.services.protocols import (
        AccountCoverageServiceProtocol,
    )
    from hasta_la_vista_money.users.models import User
    from hasta_la_vista_money.users.repositories.accounting_completeness_repository import (  # noqa: E501
        AccountingCompletenessRepository,
    )

UNRESOLVED_DECISIONS = frozenset(
    {
        BankStatementRow.Decision.PENDING,
        BankStatementRow.Decision.AWAITING_MARKUP,
        BankStatementRow.Decision.NEEDS_TRANSFER,
        BankStatementRow.Decision.DEFERRED,
        BankStatementRow.Decision.SKIPPED,
        BankStatementRow.Decision.PARSE_ERROR,
        BankStatementRow.Decision.EXPIRED,
    },
)

_PROBLEM_BY_DECISION: dict[str, str] = {
    BankStatementRow.Decision.PENDING.value: 'pending',
    BankStatementRow.Decision.AWAITING_MARKUP.value: 'incomplete_markup',
    BankStatementRow.Decision.NEEDS_TRANSFER.value: 'repayment',
    BankStatementRow.Decision.DEFERRED.value: 'deferred',
    BankStatementRow.Decision.SKIPPED.value: 'deferred',
    BankStatementRow.Decision.PARSE_ERROR.value: 'parse_error',
    BankStatementRow.Decision.EXPIRED.value: 'expired',
}

_DIRECTION_VALUES = frozenset(BankStatementRow.TransactionType.values)


@dataclass(frozen=True, kw_only=True)
class ProcessingEvidence:
    """What one upload proves about row-by-row processing."""

    upload_id: int
    status: str
    rows_saved: int
    traceability_version: int
    verified_at: object | None
    verified: bool
    reason_code: str
    requires_reupload: bool
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    reconciliation_only: bool = False
    upload_created_at: object | None = None
    upload_updated_at: object | None = None


@dataclass(frozen=True, kw_only=True)
class ProblemCount:
    """One concrete kind of unresolved problem in the selected period."""

    code: str
    count: int


@dataclass(frozen=True, kw_only=True)
class KnownAmount:
    """Known unposted amount, never mixed across currencies."""

    currency: str
    direction: str
    amount: Decimal


@dataclass(frozen=True, kw_only=True)
class AmountSummary:
    known: tuple[KnownAmount, ...]
    incomplete: bool
    unknown_count: int


@dataclass(frozen=True, kw_only=True)
class ExclusionSummary:
    count: int
    reasons: tuple[str, ...]
    amounts: tuple[KnownAmount, ...]
    amounts_known: bool


@dataclass(frozen=True, kw_only=True)
class BalanceAttention:
    """Projection of ticket 09's guard; no second retained blocker state."""

    checked: bool
    blocked: bool
    reason: str


@dataclass(frozen=True, kw_only=True)
class BalanceBlockProjection:
    """Read-only projection of ticket 09's retained finality guard."""

    block: object | None
    checked: bool


@dataclass(frozen=True, kw_only=True)
class CompletenessWarning:
    """Concrete user-facing reason, never a confidence percentage."""

    code: str
    message: str
    account_id: int | None = None


@dataclass(frozen=True, kw_only=True)
class AccountCompleteness:
    account_id: int
    account_name: str
    currency: str
    coverage: CoverageSummary
    coverage_required: bool
    processing: tuple[ProcessingEvidence, ...]
    processing_verified: bool
    processing_reasons: tuple[str, ...]
    latest_upload: ProcessingEvidence | None
    problems: tuple[ProblemCount, ...]
    unresolved_count: int
    probable_duplicate_count: int
    amounts: AmountSummary
    exclusions: ExclusionSummary
    balance: BalanceAttention
    blockers: tuple[str, ...]
    can_finalize: bool


@dataclass(frozen=True, kw_only=True)
class AccountingCompletenessResult:
    owner_id: int
    period_start: date
    period_end: date
    accounts: tuple[AccountCompleteness, ...]
    total_known_amounts: tuple[KnownAmount, ...]
    blockers: tuple[str, ...]
    warnings: tuple[CompletenessWarning, ...]
    can_finalize: bool
    balance_block: object | None = None


def _row_day(row: BankStatementRow) -> date | None:
    if row.bank_calendar_date is not None:
        return row.bank_calendar_date
    moment = row.transaction_date
    if moment is None:
        return None
    return local_calendar_date(moment)


def _row_in_period(
    row: BankStatementRow,
    period_start: date,
    period_end: date,
) -> bool:
    day = _row_day(row)
    return day is None or period_start <= day <= period_end


def _upload_in_period(
    upload: BankStatementUpload,
    period_start: date,
    period_end: date,
) -> bool:
    start = upload.statement_period_start
    end = upload.statement_period_end
    if start is not None and end is not None:
        return start <= period_end and end >= period_start
    if start is not None:
        return start <= period_end
    if end is not None:
        return end >= period_start
    return True


def _data_gone(
    upload: BankStatementUpload,
    row: BankStatementRow,
) -> bool:
    if row.data_cleaned_at is not None:
        return True
    if upload.retention_cleaned_at is not None:
        return (
            row.amount is None
            and row.transaction_date is None
            and row.bank_calendar_date is None
        )
    return False


def _format_windows(windows: Sequence[DateWindow]) -> str:
    return ', '.join(
        f'{window.start:%d.%m.%Y}—{window.end:%d.%m.%Y}' for window in windows
    )


@dataclass
class _RowTally:
    """Mutable per-account accumulator, kept out of the main assessment."""

    currency: str
    problems: dict[str, int] = field(default_factory=dict)
    unresolved_count: int = 0
    probable_duplicate_count: int = 0
    unknown_amount_count: int = 0
    amounts: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    excluded_reasons: list[str] = field(default_factory=list)
    excluded_amounts: dict[tuple[str, str], Decimal] = field(
        default_factory=dict,
    )
    excluded_count: int = 0
    excluded_amounts_known: bool = True
    recovery_rows: int = 0

    def add(
        self,
        upload: BankStatementUpload,
        row: BankStatementRow,
    ) -> None:
        if row.decision == BankStatementRow.Decision.EXCLUDED:
            self._add_excluded(upload, row)
            return
        if row.decision not in UNRESOLVED_DECISIONS:
            return
        self.unresolved_count += 1
        if row.candidate_id is not None:
            self.probable_duplicate_count += 1
        if _data_gone(upload, row):
            self.recovery_rows += 1
            self.unknown_amount_count += 1
            return
        code = _PROBLEM_BY_DECISION[row.decision]
        self.problems[code] = self.problems.get(code, 0) + 1
        self._add_known_amount(row)

    def _add_excluded(
        self,
        upload: BankStatementUpload,
        row: BankStatementRow,
    ) -> None:
        self.excluded_count += 1
        reason = row.decision_reason.strip()
        if reason and reason not in self.excluded_reasons:
            self.excluded_reasons.append(reason)
        direction = row.transaction_type
        if (
            row.amount is not None
            and not _data_gone(upload, row)
            and direction in _DIRECTION_VALUES
            and direction is not None
        ):
            key = (self.currency, direction)
            self.excluded_amounts[key] = (
                self.excluded_amounts.get(key, Decimal(0)) + row.amount
            )
        else:
            self.excluded_amounts_known = False

    def _add_known_amount(self, row: BankStatementRow) -> None:
        day = _row_day(row)
        direction = row.transaction_type
        if (
            row.amount is None
            or direction is None
            or direction not in _DIRECTION_VALUES
            or day is None
        ):
            self.unknown_amount_count += 1
            return
        key = (self.currency, direction)
        self.amounts[key] = self.amounts.get(key, Decimal(0)) + row.amount

    def finish(self) -> None:
        if self.recovery_rows:
            self.problems['restore_required'] = (
                self.problems.get('restore_required', 0) + 1
            )

    def problem_items(self) -> tuple[ProblemCount, ...]:
        return tuple(
            ProblemCount(code=code, count=count)
            for code, count in sorted(self.problems.items())
        )

    def amount_summary(self) -> AmountSummary:
        return AmountSummary(
            known=tuple(
                KnownAmount(
                    currency=currency,
                    direction=direction,
                    amount=amount,
                )
                for (currency, direction), amount in sorted(
                    self.amounts.items(),
                )
            ),
            incomplete=self.unknown_amount_count > 0,
            unknown_count=self.unknown_amount_count,
        )

    def exclusion_summary(self) -> ExclusionSummary:
        return ExclusionSummary(
            count=self.excluded_count,
            reasons=tuple(self.excluded_reasons),
            amounts=tuple(
                KnownAmount(
                    currency=currency,
                    direction=direction,
                    amount=amount,
                )
                for (currency, direction), amount in sorted(
                    self.excluded_amounts.items(),
                )
            ),
            amounts_known=self.excluded_amounts_known,
        )


class AccountingCompletenessService:
    """Assess coverage, processing proof and unresolved obstacles."""

    def __init__(
        self,
        *,
        coverage_service: AccountCoverageServiceProtocol,
        repository: AccountingCompletenessRepository,
        balance_provider: object | None = None,
    ) -> None:
        self.coverage_service = coverage_service
        self.repository = repository
        self.balance_provider = balance_provider

    def assess(
        self,
        *,
        owner: User,
        account_ids: Sequence[int] | None = None,
        period_start: date,
        period_end: date,
        balance_provider: object | None = None,
    ) -> AccountingCompletenessResult:
        if period_start > period_end:
            raise ValidationError(
                _('Начало периода не может быть позже конца'),
            )

        requested_ids = list(dict.fromkeys(account_ids or ()))
        accounts = list(
            self.repository.accounts_for_owner(
                owner,
                requested_ids or None,
            ),
        )
        if requested_ids and {account.pk for account in accounts} != set(
            requested_ids,
        ):
            raise PermissionDenied(
                _('Выбраны счета другого пользователя'),
            )

        uploads = list(
            self.repository.uploads_for_accounts(
                [account.pk for account in accounts],
            ),
        )
        rows = list(
            self.repository.rows_for_uploads([upload.pk for upload in uploads]),
        )
        uploads_by_account: dict[int, list[BankStatementUpload]] = defaultdict(
            list,
        )
        for upload in uploads:
            uploads_by_account[upload.account_id].append(upload)
        rows_by_upload: dict[int, list[BankStatementRow]] = defaultdict(list)
        for row in rows:
            rows_by_upload[row.upload_id].append(row)

        provider = (
            balance_provider
            if balance_provider is not None
            else self.balance_provider
        )
        balance_block = self._balance_block(
            owner=owner,
            account_ids=[account.pk for account in accounts],
            period_start=period_start,
            period_end=period_end,
            provider=provider,
        )

        results = tuple(
            self._account_result(
                account=account,
                uploads=uploads_by_account[account.pk],
                rows_by_upload=rows_by_upload,
                period_start=period_start,
                period_end=period_end,
                balance_block=balance_block,
                balance_checked=provider is not None,
            )
            for account in accounts
        )
        warnings = self._warnings(
            results,
            balance_checked=provider is not None,
        )
        blockers = tuple(
            dict.fromkeys(
                blocker for result in results for blocker in result.blockers
            ),
        )
        if not results:
            warnings = (
                *warnings,
                CompletenessWarning(
                    code='no_accounts',
                    message=str(_('Не выбраны счета для оценки полноты')),
                ),
            )
        return AccountingCompletenessResult(
            owner_id=owner.pk,
            period_start=period_start,
            period_end=period_end,
            accounts=results,
            total_known_amounts=self._total_known_amounts(results),
            blockers=blockers,
            warnings=warnings,
            can_finalize=bool(results) and not blockers,
            balance_block=balance_block,
        )

    def balance_block(
        self,
        *,
        owner: User,
        account_ids: Sequence[int] | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
        provider: object | None = None,
    ) -> BalanceBlockProjection:
        """Return ticket 09's retained guard without a full assessment."""
        requested_ids = list(dict.fromkeys(account_ids or ()))
        accounts = list(
            self.repository.accounts_for_owner(
                owner,
                requested_ids or None,
            ),
        )
        if requested_ids and {account.pk for account in accounts} != set(
            requested_ids,
        ):
            raise PermissionDenied(
                _('Выбраны счета другого пользователя'),
            )
        active = provider if provider is not None else self.balance_provider
        block = self._balance_block(
            owner=owner,
            account_ids=[account.pk for account in accounts],
            period_start=period_start,
            period_end=period_end,
            provider=active,
        )
        return BalanceBlockProjection(block=block, checked=active is not None)

    def _account_result(
        self,
        *,
        account: Account,
        uploads: list[BankStatementUpload],
        rows_by_upload: dict[int, list[BankStatementRow]],
        period_start: date,
        period_end: date,
        balance_block: object | None,
        balance_checked: bool,
    ) -> AccountCompleteness:
        coverage = self.coverage_service.summary(
            account=account,
            period_start=period_start,
            period_end=period_end,
        )
        coverage_required = coverage.applicable_period is not None
        coverage_ok = coverage.fully_covered or not coverage_required
        processing, tally = self._collect_rows(
            account=account,
            uploads=uploads,
            rows_by_upload=rows_by_upload,
            period_start=period_start,
            period_end=period_end,
        )
        tally.finish()
        processing_verified = all(item.verified for item in processing)
        processing_reasons = tuple(
            dict.fromkeys(
                item.reason_code for item in processing if not item.verified
            ),
        )
        latest_upload = processing[-1] if processing else None
        account_block = self._block_for_account(
            balance_block=balance_block,
            uploads=uploads,
            period_start=period_start,
            period_end=period_end,
        )
        balance = BalanceAttention(
            checked=balance_checked,
            blocked=account_block is not None,
            reason=(
                self._balance_reason(account_block)
                if account_block is not None
                else (
                    'no_unexplained_mismatch'
                    if balance_checked
                    else 'balance_verification_not_integrated'
                )
            ),
        )
        blockers: list[str] = []
        if not coverage_ok:
            blockers.append('coverage_gap')
        if not processing_verified:
            blockers.append('processing_not_proven')
        if tally.unresolved_count:
            blockers.append('unresolved_problems')
        if balance.blocked:
            blockers.append('balance_discrepancy')

        return AccountCompleteness(
            account_id=account.pk,
            account_name=account.name_account,
            currency=account.currency,
            coverage=coverage,
            coverage_required=coverage_required,
            processing=processing,
            processing_verified=processing_verified,
            processing_reasons=processing_reasons,
            latest_upload=latest_upload,
            problems=tally.problem_items(),
            unresolved_count=tally.unresolved_count,
            probable_duplicate_count=tally.probable_duplicate_count,
            amounts=tally.amount_summary(),
            exclusions=tally.exclusion_summary(),
            balance=balance,
            blockers=tuple(blockers),
            can_finalize=not blockers,
        )

    def _collect_rows(
        self,
        *,
        account: Account,
        uploads: list[BankStatementUpload],
        rows_by_upload: dict[int, list[BankStatementRow]],
        period_start: date,
        period_end: date,
    ) -> tuple[tuple[ProcessingEvidence, ...], _RowTally]:
        processing: list[ProcessingEvidence] = []
        tally = _RowTally(currency=account.currency)
        for upload in uploads:
            if not _upload_in_period(upload, period_start, period_end):
                continue
            all_rows = rows_by_upload[upload.pk]
            processing.append(
                self.processing_evidence(upload, rows_saved=len(all_rows)),
            )
            for row in all_rows:
                if _row_in_period(row, period_start, period_end):
                    tally.add(upload, row)
        return tuple(processing), tally

    def processing_evidence(
        self,
        upload: BankStatementUpload,
        *,
        rows_saved: int,
    ) -> ProcessingEvidence:
        """Prove processing only with the parser's traceability version."""
        version = upload.processing_traceability_version
        verified_at = upload.processing_verified_at
        if upload.status == BankStatementUpload.Status.FAILED:
            return self._evidence(
                upload,
                rows_saved=rows_saved,
                version=version,
                verified_at=verified_at,
                verified=False,
                reason_code='upload_failed',
            )
        if version < 1:
            return self._evidence(
                upload,
                rows_saved=rows_saved,
                version=version,
                verified_at=verified_at,
                verified=False,
                reason_code=(
                    'legacy_no_saved_rows'
                    if rows_saved == 0
                    else 'legacy_untraceable_parser'
                ),
            )
        if verified_at is None:
            return self._evidence(
                upload,
                rows_saved=rows_saved,
                version=version,
                verified_at=verified_at,
                verified=False,
                reason_code='processing_not_verified',
            )
        return self._evidence(
            upload,
            rows_saved=rows_saved,
            version=version,
            verified_at=verified_at,
            verified=True,
            reason_code='',
        )

    @staticmethod
    def _evidence(
        upload: BankStatementUpload,
        *,
        rows_saved: int,
        version: int,
        verified_at: object | None,
        verified: bool,
        reason_code: str,
    ) -> ProcessingEvidence:
        return ProcessingEvidence(
            upload_id=upload.pk,
            status=upload.status,
            rows_saved=rows_saved,
            traceability_version=version,
            verified_at=verified_at,
            verified=verified,
            reason_code=reason_code,
            requires_reupload=not verified,
            statement_period_start=upload.statement_period_start,
            statement_period_end=upload.statement_period_end,
            reconciliation_only=upload.reconciliation_only,
            upload_created_at=upload.created_at,
            upload_updated_at=upload.updated_at,
        )

    @staticmethod
    def _block_for_account(
        *,
        balance_block: object | None,
        uploads: list[BankStatementUpload],
        period_start: date,
        period_end: date,
    ) -> object | None:
        """Project the global retained block onto this account's uploads."""
        if balance_block is None:
            return None
        upload_ids = getattr(balance_block, 'upload_ids', None)
        if upload_ids is None:
            # A provider without upload identifiers cannot be narrowed.
            return balance_block
        relevant = {
            upload.pk
            for upload in uploads
            if _upload_in_period(upload, period_start, period_end)
        }
        return balance_block if relevant.intersection(upload_ids) else None

    @staticmethod
    def _balance_reason(balance_block: object) -> str:
        reason = getattr(balance_block, 'reason', '')
        if reason:
            return str(reason)
        reasons = getattr(balance_block, 'reasons', ())
        return str(next(iter(reasons), 'balance_unexplained_mismatch'))

    def _balance_block(
        self,
        *,
        owner: User,
        account_ids: Sequence[int],
        period_start: date | None,
        period_end: date | None,
        provider: object | None,
    ) -> object | None:
        if provider is None:
            return None
        method = getattr(provider, 'final_reconciliation_block', None)
        if method is None:
            raise TypeError(
                'balance provider has no final_reconciliation_block',
            )
        return cast(
            'object | None',
            method(
                user_id=owner.pk,
                account_ids=account_ids,
                period_start=period_start,
                period_end=period_end,
            ),
        )

    @staticmethod
    def _total_known_amounts(
        results: Sequence[AccountCompleteness],
    ) -> tuple[KnownAmount, ...]:
        totals: dict[tuple[str, str], Decimal] = defaultdict(
            lambda: Decimal(0),
        )
        for result in results:
            for amount in result.amounts.known:
                totals[(amount.currency, amount.direction)] += amount.amount
        return tuple(
            KnownAmount(
                currency=currency,
                direction=direction,
                amount=amount,
            )
            for (currency, direction), amount in sorted(totals.items())
        )

    @staticmethod
    def _warnings(
        results: Sequence[AccountCompleteness],
        *,
        balance_checked: bool,
    ) -> tuple[CompletenessWarning, ...]:
        warnings: list[CompletenessWarning] = []
        for result in results:
            if result.coverage.gaps:
                warnings.append(
                    CompletenessWarning(
                        code='coverage_gap',
                        account_id=result.account_id,
                        message=str(
                            _('%(account)s: нет покрытия за %(period)s')
                            % {
                                'account': result.account_name,
                                'period': _format_windows(result.coverage.gaps),
                            },
                        ),
                    ),
                )
            if not result.processing_verified:
                warnings.append(
                    CompletenessWarning(
                        code='processing_not_proven',
                        account_id=result.account_id,
                        message=str(
                            _(
                                '%(account)s: обработка выписки не доказана '
                                '(%(reason)s); нужна повторная проверка или '
                                'загрузка',
                            )
                            % {
                                'account': result.account_name,
                                'reason': ', '.join(result.processing_reasons),
                            },
                        ),
                    ),
                )
            if result.unresolved_count:
                warnings.append(
                    CompletenessWarning(
                        code='unresolved_problems',
                        account_id=result.account_id,
                        message=str(
                            _('%(account)s: нерешённых проблем — %(count)s')
                            % {
                                'account': result.account_name,
                                'count': result.unresolved_count,
                            },
                        ),
                    ),
                )
            if result.probable_duplicate_count:
                warnings.append(
                    CompletenessWarning(
                        code='probable_duplicate_caveat',
                        account_id=result.account_id,
                        message=str(
                            _(
                                '%(account)s: вероятные дубли (%(count)s) '
                                'не доказывают отсутствие движения',
                            )
                            % {
                                'account': result.account_name,
                                'count': result.probable_duplicate_count,
                            },
                        ),
                    ),
                )
            if result.amounts.incomplete:
                warnings.append(
                    CompletenessWarning(
                        code='amounts_incomplete',
                        account_id=result.account_id,
                        message=str(
                            _(
                                '%(account)s: суммы известны не полностью '
                                '(%(count)s строк)',
                            )
                            % {
                                'account': result.account_name,
                                'count': result.amounts.unknown_count,
                            },
                        ),
                    ),
                )
            if result.exclusions.count:
                warnings.append(
                    CompletenessWarning(
                        code='exclusions_caveat',
                        account_id=result.account_id,
                        message=str(
                            _('%(account)s: исключено строк — %(count)s')
                            % {
                                'account': result.account_name,
                                'count': result.exclusions.count,
                            },
                        ),
                    ),
                )
            if result.balance.blocked:
                warnings.append(
                    CompletenessWarning(
                        code='balance_discrepancy',
                        account_id=result.account_id,
                        message=str(
                            _(
                                '%(account)s: известное необъяснённое '
                                'расхождение остатка',
                            )
                            % {'account': result.account_name},
                        ),
                    ),
                )
        if results and not balance_checked:
            warnings.append(
                CompletenessWarning(
                    code='balance_verification_not_integrated',
                    message=str(
                        _(
                            'Проверка банковского остатка не подключена; '
                            'отсутствие остатка не считается нулём',
                        ),
                    ),
                ),
            )
        return tuple(warnings)
