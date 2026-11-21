"""Accounting control entry: five independent measurements.

Coverage, row resolution, bank data availability, technical processing and
the balance check are reported separately. No measurement proves another.
"""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from django.utils.translation import gettext as _

from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
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


@dataclass(frozen=True)
class RowResolution:
    """Resolution counts of the statement rows in the selected period."""

    awaiting_markup: int
    pending: int
    needs_transfer: int
    resolved: int
    legacy_skips: int
    expired: int


@dataclass(frozen=True)
class BalanceCheck:
    """The balance measurement; never inferred from other measurements."""

    checked: bool
    label: str
    detail: str


@dataclass(frozen=True)
class AccountingControlSummary:
    """Five separate measurements for one account period."""

    uploads: tuple[UploadControl, ...]
    rows: RowResolution
    exclusions: tuple[BankStatementRow, ...]
    coverage: CoverageSummary
    balance: BalanceCheck
    adapter_note: str


class AccountingControlService:
    """Build the five separate accounting control measurements."""

    def __init__(self, coverage_service: StatementCoverageService) -> None:
        """Initialise the service with the coverage service.

        Args:
            coverage_service: Independent period coverage service.
        """
        self._coverage_service = coverage_service

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
                legacy_skips=int(row_counts['legacy_skips'] or 0),
                expired=int(row_counts['expired'] or 0),
            ),
            exclusions=exclusions,
            coverage=self._coverage_service.summary(
                account,
                period_start,
                period_end,
            ),
            balance=BalanceCheck(
                checked=False,
                label=str(_('Не проверено')),
                detail=str(
                    _(
                        'Проверка остатка не входит в этот срез; '
                        'расхождение не заявляется.',
                    ),
                ),
            ),
            adapter_note=str(
                _(
                    'Адаптеры этого среза: РосДорБанк. Райффайзен, Сбербанк, '
                    'Ozon и generic не покрыты этим срезом и требуют '
                    'проверки.',
                ),
            ),
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
        explicit_period = queryset.filter(
            period_coverages__period_start__lte=period_end,
            period_coverages__period_end__gte=period_start,
        )
        unknown_period = queryset.filter(
            period_coverages__isnull=True,
        ).filter(
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
            (explicit_period | unknown_period)
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
        )
