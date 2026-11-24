"""Accounting control entry: five independent measurements.

Coverage, row resolution, bank data availability, technical processing and
the balance check are reported separately. No measurement proves another.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from hasta_la_vista_money.finance_account.models import (
    StatementPeriodCoverage,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
)
from hasta_la_vista_money.users.services.statement_balance_verification import (
    BalanceVerificationState,
    StatementBalanceVerificationService,
)
from hasta_la_vista_money.users.services.statement_coverage import (
    CoverageSummary,
    StatementCoverageService,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import Account

RESOLVED_DECISIONS = (
    BankStatementRow.Decision.NEW,
    BankStatementRow.Decision.LINKED,
    BankStatementRow.Decision.TRANSFERRED,
    BankStatementRow.Decision.NOT_A_PAYMENT,
    BankStatementRow.Decision.MUTUAL_CANCEL,
)


@dataclass(frozen=True)
class UploadControl:
    """Technical processing and bank data state of one upload."""

    upload: BankStatementUpload
    has_markup_rows: bool
    markup_label: str
    data_available: bool
    data_label: str
    awaiting_markup: int
    requires_legacy_review: bool
    legacy_review_label: str
    empty_parse: bool
    empty_parse_label: str


@dataclass(frozen=True)
class RowResolution:
    """Resolution counts of the statement rows in the selected period."""

    awaiting_markup: int
    pending: int
    needs_transfer: int
    resolved: int
    duplicates: int
    legacy_skips: int
    expired: int


@dataclass(frozen=True)
class BalanceCheck:
    """The balance measurement; never inferred from other measurements."""

    checked: bool
    actual: bool
    result: str
    reason: str
    label: str
    detail: str
    moment: datetime | None
    currency: str
    bank_balance: Decimal | None
    ledger_balance: Decimal | None
    discrepancy: Decimal | None
    has_amounts: bool
    explanation_code: str
    explanation_completeness: str
    blocks_final_reconciliation: bool


@dataclass(frozen=True)
class AccountingControlSummary:
    """Five separate measurements for one account period."""

    uploads: tuple[UploadControl, ...]
    rows: RowResolution
    exclusions: tuple[BankStatementRow, ...]
    coverage: CoverageSummary
    balance: BalanceCheck
    balance_checks: tuple[BalanceVerificationState, ...]
    adapter_note: str


class AccountingControlService:
    """Build the five separate accounting control measurements."""

    def __init__(
        self,
        coverage_service: StatementCoverageService,
        balance_verification_service: StatementBalanceVerificationService,
    ) -> None:
        """Initialise the service with the coverage and balance services.

        Args:
            coverage_service: Independent period coverage service.
            balance_verification_service: Statement balance checks.
        """
        self._coverage_service = coverage_service
        self._balance_verification_service = balance_verification_service

    def build(
        self,
        account: 'Account',
        period_start: date,
        period_end: date,
    ) -> AccountingControlSummary:
        """Build the control summary for one account period.

        Args:
            account: Account to inspect.
            period_start: First day of the selected period.
            period_end: Last day of the selected period.

        Returns:
            Separately measured control summary.
        """
        uploads = self._uploads(account.pk, period_start, period_end)
        upload_ids = [upload.pk for upload in uploads]
        rows = BankStatementRow.objects.filter(
            upload_id__in=upload_ids,
        ).filter(
            Q(transaction_date__isnull=True)
            | Q(
                transaction_date__date__range=(
                    period_start,
                    period_end,
                ),
            ),
        )
        row_counts = rows.aggregate(
            awaiting_markup=Count(
                'pk',
                filter=Q(
                    decision=BankStatementRow.Decision.AWAITING_MARKUP,
                ),
            ),
            pending=Count(
                'pk',
                filter=Q(decision=BankStatementRow.Decision.PENDING),
            ),
            needs_transfer=Count(
                'pk',
                filter=Q(decision=BankStatementRow.Decision.NEEDS_TRANSFER),
            ),
            resolved=Count('pk', filter=Q(decision__in=RESOLVED_DECISIONS)),
            duplicates=Count(
                'pk',
                filter=Q(decision=BankStatementRow.Decision.DUPLICATE),
            ),
            legacy_skips=Count(
                'pk',
                filter=Q(decision=BankStatementRow.Decision.SKIPPED)
                & ~Q(
                    exclusion_code__in=BankStatementRow.ExclusionCode.values,
                ),
            ),
            expired=Count(
                'pk',
                filter=Q(decision=BankStatementRow.Decision.EXPIRED),
            ),
        )
        exclusions = tuple(
            rows.filter(
                decision=BankStatementRow.Decision.SKIPPED,
                exclusion_code__in=BankStatementRow.ExclusionCode.values,
            ).order_by('transaction_date', 'pk'),
        )
        awaiting_by_upload = dict(
            rows.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            )
            .values_list('upload_id')
            .annotate(count=Count('pk')),
        )
        balance_checks = tuple(
            self._balance_verification_service.describe(
                self._balance_verification_service.refresh_actuality(upload),
            )
            for upload in uploads
        )
        return AccountingControlSummary(
            uploads=tuple(
                self._upload_control(upload, awaiting_by_upload)
                for upload in uploads
            ),
            rows=RowResolution(
                awaiting_markup=int(row_counts['awaiting_markup'] or 0),
                pending=int(row_counts['pending'] or 0),
                needs_transfer=int(row_counts['needs_transfer'] or 0),
                resolved=int(row_counts['resolved'] or 0),
                duplicates=int(row_counts['duplicates'] or 0),
                legacy_skips=int(row_counts['legacy_skips'] or 0),
                expired=int(row_counts['expired'] or 0),
            ),
            exclusions=exclusions,
            coverage=self._coverage_service.summary(
                account,
                period_start,
                period_end,
            ),
            balance=self._balance_summary(balance_checks),
            balance_checks=balance_checks,
            adapter_note=str(
                _(
                    'Поддержаны выписки Райффайзена, Сбербанка, Ozon и '
                    'РосДорБанка, а также табличные выписки без банковской '
                    'идентичности. Незнакомый формат требует ручной '
                    'проверки: полнота автоматически не заявляется.',
                ),
            ),
        )

    @staticmethod
    def _balance_summary(
        checks: tuple[BalanceVerificationState, ...],
    ) -> BalanceCheck:
        """Aggregate per-upload checks without hiding an unexplained gap."""
        active = [check for check in checks if check.checked]
        latest = active[0] if active else None
        unchecked = any(not check.checked for check in checks)
        blocks = any(check.blocks_final_reconciliation for check in checks)
        stale = any(not check.actual for check in active)
        explained = any(
            check.result == BankStatementUpload.BalanceResult.DISCREPANCY
            and check.explanation_code
            and check.actual
            for check in active
        )
        matched = any(
            check.result == BankStatementUpload.BalanceResult.MATCHED
            and check.actual
            for check in active
        )
        result: str
        if not latest:
            label = _('Не проверено')
            result = BankStatementUpload.BalanceResult.NOT_CHECKED
        elif blocks:
            label = _('Расхождение')
            result = BankStatementUpload.BalanceResult.DISCREPANCY
        elif unchecked:
            label = _('Не проверено')
            result = BankStatementUpload.BalanceResult.NOT_CHECKED
        elif stale:
            label = _('Требует перепроверки')
            result = latest.result
        elif explained:
            label = _('Расхождение объяснено')
            result = BankStatementUpload.BalanceResult.DISCREPANCY
        elif matched:
            label = _('Совпадает')
            result = BankStatementUpload.BalanceResult.MATCHED
        else:
            label = _('Не проверено')
            result = BankStatementUpload.BalanceResult.NOT_CHECKED
        details = tuple(check.detail for check in active if check.detail)
        return BalanceCheck(
            checked=bool(active) and not unchecked,
            actual=bool(active) and not stale and not unchecked,
            result=result,
            reason=latest.reason if latest else '',
            label=str(label),
            detail=' · '.join(details),
            moment=latest.moment if latest else None,
            currency=latest.currency if latest else '',
            bank_balance=latest.bank_balance if latest else None,
            ledger_balance=latest.ledger_balance if latest else None,
            discrepancy=latest.discrepancy if latest else None,
            has_amounts=latest.has_amounts if latest else False,
            explanation_code=latest.explanation_code if latest else '',
            explanation_completeness=(latest.completeness if latest else ''),
            blocks_final_reconciliation=blocks,
        )

    @staticmethod
    def _uploads(
        account_id: int,
        period_start: date,
        period_end: date,
    ) -> list[BankStatementUpload]:
        """Return uploads whose explicit period or run date intersects."""
        queryset = (
            BankStatementUpload.objects.filter(account_id=account_id)
            .select_related('account')
            .annotate(
                has_markup_rows=Exists(
                    BankStatementRow.objects.filter(
                        upload_id=OuterRef('pk'),
                    ).exclude(kind=''),
                ),
            )
        )
        valid_upload_period = (
            Q(statement_period_from__isnull=False)
            & Q(statement_period_to__isnull=False)
            & Q(statement_period_from__lte=F('statement_period_to'))
        )
        explicit_period = queryset.filter(
            valid_upload_period,
            statement_period_from__lte=period_end,
            statement_period_to__gte=period_start,
        )
        # Older uploads may predate the stored bounds. Only their actual
        # bank statement confirmation keeps them in the historical report;
        # a revised, non-actual interval never does.
        legacy_coverage_period = queryset.filter(
            ~valid_upload_period,
            period_coverages__is_actual=True,
            period_coverages__source=(
                StatementPeriodCoverage.Source.BANK_STATEMENT
            ),
            period_coverages__upload__isnull=False,
            period_coverages__period_start__lte=period_end,
            period_coverages__period_end__gte=period_start,
        )
        unknown_period = queryset.filter(~valid_upload_period).filter(
            Q(created_at__date__range=(period_start, period_end))
            | Q(
                statement_rows__transaction_date__date__range=(
                    period_start,
                    period_end,
                ),
            )
            | Q(
                statement_rows__transaction_date__isnull=True,
                statement_rows__pk__isnull=False,
            ),
        )
        return list(
            (explicit_period | legacy_coverage_period | unknown_period)
            .distinct()
            .order_by('-created_at'),
        )

    @staticmethod
    def _upload_control(
        upload: BankStatementUpload,
        awaiting_by_upload: dict[int, int],
    ) -> UploadControl:
        """Describe technical processing and data availability of an upload."""
        data_available = (
            upload.expires_at > timezone.now()
            and upload.retention_cleaned_at is None
        )
        has_markup_rows = bool(getattr(upload, 'has_markup_rows', False))
        requires_legacy_review = (
            upload.legacy_review_state
            == BankStatementUpload.LegacyReviewState.REQUIRES_REVIEW
        )
        if requires_legacy_review:
            reason = (
                upload.get_legacy_review_reason_display()
                if upload.legacy_review_reason
                else _('Причина не установлена')
            )
            legacy_label = _('Требует проверки: %(reason)s') % {
                'reason': reason,
            }
        else:
            legacy_label = ''
        empty_parse = upload.total_transactions == 0 and upload.status in {
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
            BankStatementUpload.Status.COMPLETED,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        }
        return UploadControl(
            upload=upload,
            has_markup_rows=has_markup_rows,
            markup_label=str(
                _('Строки разметки этого среза сохранены')
                if has_markup_rows
                else _('Не покрыт этим срезом — требует проверки'),
            ),
            data_available=data_available,
            data_label=str(
                _('Данные доступны')
                if data_available
                else _('Данные очищены или срок истёк'),
            ),
            awaiting_markup=int(awaiting_by_upload.get(upload.pk, 0)),
            requires_legacy_review=requires_legacy_review,
            legacy_review_label=str(legacy_label),
            empty_parse=empty_parse,
            empty_parse_label=str(
                _(
                    'Пустой разбор: операции не найдены, покрытие не '
                    'подтверждено.',
                )
                if empty_parse
                else '',
            ),
        )
