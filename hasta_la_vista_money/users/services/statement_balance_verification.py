"""Verify a historical bank balance without correcting any money.

The reconstructed balance from :class:`BalanceHistoryService` is a Decimal,
not a proof. A comparison is conclusive only when the bank balance moment,
its meaning and the movement data are known; otherwise the result is
``unknown`` with a machine reason. The unexplained mismatch flag is retained
independently of the last result and of retention, and it is the final
reconciliation guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.movement_source import DepositMovementSource
from hasta_la_vista_money.finance_account.services.balance_history_service import (  # noqa: E501
    BalanceHistoryService,
)
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import (
    audit_operation,
    current_operation_id,
    current_operation_kind,
)
from hasta_la_vista_money.users.models import BankStatementUpload
from hasta_la_vista_money.users.repositories.statement_balance_verification_repository import (  # noqa: E501
    StatementBalanceVerificationRepository,
)
from hasta_la_vista_money.users.services.statement_balance_staleness import (
    mark_balance_checks_stale,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from hasta_la_vista_money.finance_account.models import Account

STATUS_UNKNOWN = 'unknown'
STATUS_VERIFIED = 'verified'
STATUS_MISMATCH = 'mismatch'
STATUS_STALE = 'stale'

REASON_NOT_CONFIGURED = 'balance_not_configured'
REASON_KIND_UNKNOWN = 'balance_kind_unknown'
REASON_MOMENT_UNKNOWN = 'balance_moment_unknown'
REASON_DAY_TIMEZONE_UNKNOWN = 'balance_day_timezone_unknown'
REASON_DAY_BOUNDARY_AMBIGUOUS = 'balance_day_boundary_ambiguous'
REASON_BANK_BALANCE_MISSING = 'bank_balance_missing'
REASON_DATA_CLEANED = 'balance_data_cleaned'
REASON_UNRESOLVED_ROWS = 'unresolved_rows'
REASON_AVAILABLE_CREDIT_UNKNOWN = 'available_credit_limit_unknown'
REASON_AVAILABLE_SEMANTICS_UNKNOWN = 'available_balance_semantics_unknown'
REASON_OPENING_BOUNDARY_UNKNOWN = 'opening_boundary_unknown'
REASON_MOVEMENT_CHANGED = 'movement_changed'
REASON_RECONFIGURED = 'balance_reconfigured'

UPLOAD_AUDIT_LABEL = 'users.BankStatementUpload'


@dataclass(frozen=True)
class BalanceVerificationResult:
    """Last historical balance comparison with its freshness."""

    upload_id: int
    status: str
    last_result: str
    reason: str
    bank_balance: Decimal | None
    app_balance: Decimal | None
    difference: Decimal | None
    bank_balance_date: date | None
    bank_balance_at: datetime | None
    kind: str
    verified_at: datetime | None
    needs_recheck: bool
    unexplained_mismatch: bool
    explained_at: datetime | None

    @property
    def blocks_final_reconciliation(self) -> bool:
        """Return whether the retained mismatch blocks finality."""
        return self.unexplained_mismatch


@dataclass(frozen=True)
class FinalReconciliationBlock:
    """Uploads whose retained mismatch forbids finishing reconciliation."""

    upload_ids: tuple[int, ...]
    reasons: tuple[str, ...]


class StatementBalanceVerificationService:
    """Compare a bank balance with the balance at the same bank moment."""

    def __init__(
        self,
        repository: StatementBalanceVerificationRepository | None = None,
        balance_history_service: BalanceHistoryService | None = None,
    ) -> None:
        self.repository = repository or StatementBalanceVerificationRepository()
        self.balance_history_service = balance_history_service or (
            BalanceHistoryService(
                movement_sources=[DepositMovementSource()],
            )
        )

    def verification(
        self,
        upload_id: int,
        user_id: int,
    ) -> BalanceVerificationResult:
        """Return the last result without recalculating anything."""
        upload = self.repository.owned_upload(upload_id, user_id)
        if upload is None:
            raise BankStatementUpload.DoesNotExist
        return self._result(upload, timezone.now())

    @transaction.atomic
    def verify(
        self,
        upload_id: int,
        user_id: int,
    ) -> BalanceVerificationResult:
        """Recalculate at the stored moment and persist the last result."""
        upload, account = self.repository.lock_owned_upload(
            upload_id,
            user_id,
        )
        now = timezone.now()
        if self._bank_data_cleaned(upload, now):
            self._persist_inconclusive(upload, REASON_DATA_CLEANED)
            return self._result(upload, now)
        bank_balance = upload.statement_closing_balance
        if bank_balance is None:
            self._persist_inconclusive(upload, REASON_BANK_BALANCE_MISSING)
            return self._result(upload, now)
        moment, reason = self._balance_moment(upload, account)
        if moment is None:
            self._persist_inconclusive(upload, reason)
            return self._result(upload, now)
        if self._has_unresolved_influencing(upload, moment):
            self._persist_inconclusive(upload, REASON_UNRESOLVED_ROWS)
            return self._result(upload, now)

        app_balance = self.balance_history_service.balance_at(account, moment)
        difference = bank_balance - app_balance
        if difference == Decimal(constants.ZERO):
            status = STATUS_VERIFIED
        else:
            status = STATUS_MISMATCH
        upload.balance_verification_status = status
        upload.balance_verified_at = now
        upload.balance_needs_recheck = False
        upload.balance_stale_reason = ''
        upload.balance_unexplained_mismatch = status == STATUS_MISMATCH
        upload.account_balance_after = app_balance
        upload.balance_discrepancy = difference
        upload.save(
            update_fields=[
                'balance_verification_status',
                'balance_verified_at',
                'balance_needs_recheck',
                'balance_stale_reason',
                'balance_unexplained_mismatch',
                'account_balance_after',
                'balance_discrepancy',
                'updated_at',
            ],
        )
        return self._result(upload, now)

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
        """Store a document- or owner-confirmed balance moment and kind."""
        if balance_at is not None and timezone.is_naive(balance_at):
            raise ValidationError(
                _('Момент банковского остатка должен содержать часовой пояс.'),
            )
        if balance_at is None and balance_date is None:
            raise ValidationError(
                _('Укажите дату или момент банковского остатка.'),
            )
        if balance_kind == BankStatementUpload.BalanceKind.UNKNOWN:
            raise ValidationError(
                _('Укажите семантику банковского остатка.'),
            )
        if balance_kind not in BankStatementUpload.BalanceKind.values:
            raise ValidationError(_('Неизвестная семантика остатка.'))
        if (
            balance_at is None
            and balance_kind
            in (
                BankStatementUpload.BalanceKind.OPENING,
                BankStatementUpload.BalanceKind.CLOSING,
                BankStatementUpload.BalanceKind.AVAILABLE,
            )
            and timezone_name
            and self._zone(timezone_name) is None
        ):
            raise ValidationError(_('Неизвестный часовой пояс остатка.'))
        with audit_operation(
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        ):
            return self._confirm(
                upload_id,
                user_id,
                balance_kind=balance_kind,
                balance_date=balance_date,
                balance_at=balance_at,
                timezone_name=timezone_name,
            )

    @transaction.atomic
    def _confirm(
        self,
        upload_id: int,
        user_id: int,
        *,
        balance_kind: str,
        balance_date: date | None,
        balance_at: datetime | None,
        timezone_name: str,
    ) -> BalanceVerificationResult:
        upload, _account = self.repository.lock_owned_upload(
            upload_id,
            user_id,
        )
        upload.statement_balance_kind = balance_kind
        upload.statement_balance_date = balance_date
        upload.statement_balance_at = balance_at
        upload.statement_balance_timezone = timezone_name
        if upload.balance_verified_at is not None:
            upload.balance_needs_recheck = True
            upload.balance_stale_reason = REASON_RECONFIGURED
        else:
            upload.balance_needs_recheck = False
            upload.balance_stale_reason = ''
        upload.save(
            update_fields=[
                'statement_balance_kind',
                'statement_balance_date',
                'statement_balance_at',
                'statement_balance_timezone',
                'balance_needs_recheck',
                'balance_stale_reason',
                'updated_at',
            ],
        )
        return self._result(upload, timezone.now())

    def explain_mismatch(
        self,
        upload_id: int,
        user_id: int,
        *,
        reason: str,
    ) -> BalanceVerificationResult:
        """Clear the unexplained flag with an owner reason and audit."""
        if not reason.strip():
            raise ValidationError(_('Укажите причину расхождения.'))
        with audit_operation(
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        ):
            return self._explain(upload_id, user_id, reason.strip())

    @transaction.atomic
    def _explain(
        self,
        upload_id: int,
        user_id: int,
        reason: str,
    ) -> BalanceVerificationResult:
        upload, _account = self.repository.lock_owned_upload(
            upload_id,
            user_id,
        )
        if not upload.balance_unexplained_mismatch:
            raise ValidationError(
                _('У этой проверки нет необъяснённого расхождения.'),
            )
        now = timezone.now()
        previous_explanation = upload.balance_explanation
        upload.balance_unexplained_mismatch = False
        upload.balance_explained_by_id = user_id
        upload.balance_explained_at = now
        upload.balance_explanation = reason
        upload.save(
            update_fields=[
                'balance_unexplained_mismatch',
                'balance_explained_by',
                'balance_explained_at',
                'balance_explanation',
                'updated_at',
            ],
        )
        AuditLog.objects.create(
            user_id=user_id,
            model_name=UPLOAD_AUDIT_LABEL,
            object_pk=str(upload.pk),
            object_name='',
            action=AuditLog.Action.UPDATE,
            diff={
                'balance_unexplained_mismatch': {
                    'old': True,
                    'new': False,
                },
                'balance_explanation': {
                    'old': previous_explanation,
                    'new': reason,
                },
            },
            operation_id=current_operation_id(),
            kind=current_operation_kind(),
        )
        return self._result(upload, now)

    def final_reconciliation_block(
        self,
        *,
        user_id: int,
        account_ids: Collection[int] | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> FinalReconciliationBlock | None:
        """Return retained unexplained mismatches that forbid finality."""
        uploads = self.repository.blocking_uploads(
            user_id,
            account_ids=account_ids,
            period_start=period_start,
            period_end=period_end,
        )
        upload_ids = tuple(uploads.values_list('pk', flat=True))
        if not upload_ids:
            return None
        return FinalReconciliationBlock(
            upload_ids=upload_ids,
            reasons=('balance_unexplained_mismatch',),
        )

    def mark_movements_changed(
        self,
        account_ids: Collection[int],
        moments: Iterable[datetime | date],
    ) -> int:
        """Require a new check after an influencing movement change."""
        return mark_balance_checks_stale(account_ids, moments)

    def _result(
        self,
        upload: BankStatementUpload,
        now: datetime,
    ) -> BalanceVerificationResult:
        cleaned = self._bank_data_cleaned(upload, now)
        last_result = upload.balance_verification_status
        needs_recheck = upload.balance_needs_recheck
        status = STATUS_STALE if needs_recheck else last_result
        reason = upload.balance_stale_reason
        bank_balance = None if cleaned else upload.statement_closing_balance
        if cleaned:
            reason = REASON_DATA_CLEANED
            app_balance = None
            difference = None
        else:
            conclusive = (
                last_result in (STATUS_VERIFIED, STATUS_MISMATCH)
                and not needs_recheck
            )
            app_balance = upload.account_balance_after if conclusive else None
            difference = upload.balance_discrepancy if conclusive else None
            if not reason:
                reason = self._derived_reason(upload)
        return BalanceVerificationResult(
            upload_id=upload.pk,
            status=status,
            last_result=last_result,
            reason=reason,
            bank_balance=bank_balance,
            app_balance=app_balance,
            difference=difference,
            bank_balance_date=upload.statement_balance_date,
            bank_balance_at=upload.statement_balance_at,
            kind=upload.statement_balance_kind,
            verified_at=upload.balance_verified_at,
            needs_recheck=needs_recheck,
            unexplained_mismatch=upload.balance_unexplained_mismatch,
            explained_at=upload.balance_explained_at,
        )

    @staticmethod
    def _derived_reason(upload: BankStatementUpload) -> str:
        if upload.statement_closing_balance is None:
            return REASON_BANK_BALANCE_MISSING
        if (
            upload.statement_balance_at is None
            and upload.statement_balance_date is None
        ):
            return REASON_NOT_CONFIGURED
        if upload.statement_balance_kind == (
            BankStatementUpload.BalanceKind.UNKNOWN
        ):
            return REASON_KIND_UNKNOWN
        return ''

    @staticmethod
    def _bank_data_cleaned(
        upload: BankStatementUpload,
        now: datetime,
    ) -> bool:
        return (
            upload.retention_cleaned_at is not None or upload.expires_at <= now
        )

    @staticmethod
    def _persist_inconclusive(
        upload: BankStatementUpload,
        reason: str,
    ) -> None:
        upload.balance_stale_reason = reason
        fields = ['balance_stale_reason', 'updated_at']
        if upload.balance_verified_at is not None:
            upload.balance_needs_recheck = True
            fields.append('balance_needs_recheck')
        upload.save(update_fields=fields)

    @staticmethod
    def _zone(name: str) -> ZoneInfo | None:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return None

    def _balance_moment(
        self,
        upload: BankStatementUpload,
        account: Account,
    ) -> tuple[datetime | None, str]:
        if upload.statement_balance_at is not None:
            return upload.statement_balance_at, ''
        return self._day_moment(upload, account)

    def _day_moment(
        self,
        upload: BankStatementUpload,
        account: Account,
    ) -> tuple[datetime | None, str]:
        balance_day = upload.statement_balance_date
        kind = upload.statement_balance_kind
        reason = self._unusable_day_reason(kind, balance_day, account)
        if reason:
            return None, reason
        if balance_day is None:
            return None, REASON_NOT_CONFIGURED
        zone = self._zone(upload.statement_balance_timezone)
        if zone is None:
            return None, REASON_DAY_TIMEZONE_UNKNOWN
        moment = self._day_boundary(kind, balance_day, zone)
        if moment is None:
            return None, REASON_OPENING_BOUNDARY_UNKNOWN
        return self._checked_moment(moment)

    @staticmethod
    def _checked_moment(moment: datetime) -> tuple[datetime | None, str]:
        offset = moment.utcoffset()
        if offset is not None and offset < timedelta(0):
            # Day-precise bank movements are anchored at UTC midnight.
            # West of UTC that anchor falls on the previous local day, so
            # an instant cannot be derived without guessing.
            return None, REASON_DAY_BOUNDARY_AMBIGUOUS
        return moment, ''

    @staticmethod
    def _unusable_day_reason(
        kind: str,
        balance_day: date | None,
        account: Account,
    ) -> str:
        if kind == BankStatementUpload.BalanceKind.UNKNOWN:
            return REASON_KIND_UNKNOWN
        if balance_day is None:
            return REASON_NOT_CONFIGURED
        if kind == BankStatementUpload.BalanceKind.AVAILABLE:
            if account.type_account in constants.CREDIT_ACCOUNT_TYPES:
                return REASON_AVAILABLE_CREDIT_UNKNOWN
            if account.type_account not in constants.LIQUID_ACCOUNT_TYPES:
                return REASON_AVAILABLE_SEMANTICS_UNKNOWN
        return ''

    @staticmethod
    def _day_boundary(
        kind: str,
        balance_day: date,
        zone: ZoneInfo,
    ) -> datetime | None:
        if kind != BankStatementUpload.BalanceKind.OPENING:
            return datetime.combine(balance_day, time.max, tzinfo=zone)
        if balance_day == date.min:
            return None
        return datetime.combine(
            balance_day - timedelta(days=1),
            time.max,
            tzinfo=zone,
        )

    def _has_unresolved_influencing(
        self,
        upload: BankStatementUpload,
        moment: datetime,
    ) -> bool:
        balance_day = upload.statement_balance_date
        opening = (
            upload.statement_balance_kind
            == BankStatementUpload.BalanceKind.OPENING
        )
        for row in self.repository.unresolved_rows(
            upload.account_id,
        ).iterator():
            row_day = row.bank_calendar_date
            if row_day is None and row.transaction_date is not None:
                row_day = timezone.localtime(row.transaction_date).date()
            if row_day is None:
                return True
            if upload.statement_balance_at is not None:
                if row_day <= timezone.localtime(moment).date():
                    return True
            elif balance_day is not None:
                if opening and row_day < balance_day:
                    return True
                if not opening and row_day <= balance_day:
                    return True
            else:
                return True
        return False
