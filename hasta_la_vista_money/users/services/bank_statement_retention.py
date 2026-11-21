"""Expire bank statement payloads while keeping financial history.

Cleanup is the only writer that removes retained bank data. It deletes the
PDF and every bank-derived row field, expires unresolved rows, scrubs only
the statement-origin copies in the audit history, and records that
anonymization with an actor and time. Decisions, movement links, technical
fingerprints and the independent financial audit stay untouched.
"""

from datetime import datetime
from typing import Any, Final

import structlog
from django.db import transaction
from django.utils import timezone

from hasta_la_vista_money.system.audit_registry import (
    TRANSACTION_LABEL,
    TRANSFER_LABEL,
)
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
)
from hasta_la_vista_money.users.protocols.services import (
    BankStatementReconciliationServiceProtocol,
)

logger = structlog.get_logger(__name__)

_UNRESOLVED_DECISIONS: Final = frozenset(
    {
        BankStatementRow.Decision.PENDING,
        BankStatementRow.Decision.NEEDS_TRANSFER,
        BankStatementRow.Decision.AWAITING_MARKUP,
    },
)

_CREATED_DECISIONS: Final = frozenset(
    {
        BankStatementRow.Decision.NEW,
        BankStatementRow.Decision.TRANSFERRED,
    },
)

# Values copied from the statement into an audit diff. Removing them keeps
# the audited operation and its identity, not the bank payload.
_BANK_COPY_FIELDS: Final = frozenset(
    {
        'amount',
        'date',
        'description',
        'exchange_date',
        'notes',
        'source_ref',
    },
)

_STATEMENT_AUDIT_KINDS: Final = frozenset(
    {
        AuditOperationKind.STATEMENT_IMPORT,
        AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        AuditOperationKind.STATEMENT_MARKUP,
    },
)

_STATEMENT_AUDIT_MODELS: Final = frozenset({TRANSACTION_LABEL, TRANSFER_LABEL})


class BankStatementRetentionService:
    """Expire statement reconciliations and remove retained bank data."""

    def __init__(
        self,
        reconciliation_service: BankStatementReconciliationServiceProtocol,
    ) -> None:
        """Initialize retention with the reconciliation counter service."""
        self.reconciliation_service = reconciliation_service

    def cleanup_expired(self, now: datetime | None = None) -> int:
        """Clean every expired upload once and return the cleaned count.

        Each upload is isolated: a storage error on one leaves that upload
        untouched for a later retry while the remaining uploads are still
        cleaned.
        """
        deadline = now or timezone.now()
        upload_ids = list(
            BankStatementUpload.objects.filter(
                expires_at__lte=deadline,
                retention_cleaned_at__isnull=True,
            ).values_list('pk', flat=True),
        )
        cleaned = 0
        for upload_id in upload_ids:
            if self._cleanup_upload(upload_id, deadline):
                cleaned += 1
        return cleaned

    def _cleanup_upload(self, upload_id: int, now: datetime) -> bool:
        """Clean one upload under its lock so a replay cannot race it.

        The deadline is re-read after the upload lock: a replay that
        attached the file and fixed a new deadline first wins and this run
        does nothing. The PDF is deleted only after that check and before
        the upload is marked cleaned, so a replay either happens before
        cleanup or restores everything in one later run.
        """
        with transaction.atomic():
            upload = (
                BankStatementUpload.objects.select_for_update()
                .select_related('account', 'user')
                .get(pk=upload_id)
            )
            if upload.retention_cleaned_at is not None:
                return False
            if upload.expires_at > now:
                return False
            rows = list(
                BankStatementRow.objects.select_for_update().filter(
                    upload=upload,
                ),
            )
            unresolved_ids = [
                row.pk for row in rows if row.decision in _UNRESOLVED_DECISIONS
            ]
            row_ids = [row.pk for row in rows]
            audit_copy_ids = self._statement_movement_ids(rows)

            file_name = upload.pdf_file.name
            if file_name:
                try:
                    upload.pdf_file.storage.delete(file_name)
                except Exception:
                    # This upload stays expired for a later retry; the rest
                    # of the batch must still be cleaned.
                    logger.exception(
                        'bank_statement_retention_storage_failed',
                        upload_id=upload.pk,
                    )
                    return False

            if unresolved_ids:
                BankStatementRow.objects.filter(
                    pk__in=unresolved_ids,
                ).update(
                    decision=BankStatementRow.Decision.EXPIRED,
                    decided_at=now,
                )
            BankStatementCandidate.objects.filter(row_id__in=row_ids).delete()
            # The technical row position is not bank payload: it is the
            # stable key a known-file replay uses to restore this row.
            BankStatementRow.objects.filter(pk__in=row_ids).update(
                transaction_type=None,
                transaction_date=None,
                amount=None,
                description='',
                candidate_description='',
                suggested_category='',
                merchant_key='',
                counterparty_account='',
                source_ref=None,
                candidate=None,
                kind='',
                match_calendar_date=False,
            )
            self._anonymize_audit_copies(audit_copy_ids)
            upload.pdf_file = ''
            upload.retention_cleaned_at = now
            upload.statement_closing_balance = None
            upload.account_balance_after = None
            upload.balance_discrepancy = None
            upload.error_message = ''
            upload.celery_task_id = ''
            upload.status = (
                BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED
                if unresolved_ids
                else (
                    BankStatementUpload.Status.FAILED
                    if upload.status == BankStatementUpload.Status.FAILED
                    else BankStatementUpload.Status.COMPLETED
                )
            )
            upload.save(
                update_fields=[
                    'pdf_file',
                    'retention_cleaned_at',
                    'status',
                    'statement_closing_balance',
                    'account_balance_after',
                    'balance_discrepancy',
                    'error_message',
                    'celery_task_id',
                ],
            )
            self._record_anonymization(
                upload,
                len(rows),
                len(unresolved_ids),
                now,
            )
            self.reconciliation_service.refresh_outcome_counts(upload)
        return True

    @staticmethod
    def _statement_movement_ids(rows: list[BankStatementRow]) -> set[int]:
        """Return movements this upload created, not ones it only linked.

        A linked row points at an independent pre-existing movement, whose
        audit history must stay untouched. Previous created movements that
        were later replaced or deleted still matter, so decision audits are
        included.
        """
        movement_ids: set[int] = set()
        for row in rows:
            _collect_created_movement(
                movement_ids,
                row.decision,
                row.transaction_id,
                row.transfer_id,
            )
        for audit in BankStatementDecisionAudit.objects.filter(
            row__in=rows,
        ):
            _collect_created_movement(
                movement_ids,
                audit.decision,
                audit.transaction_id,
                audit.transfer_id,
            )
            _collect_created_movement(
                movement_ids,
                audit.previous_decision,
                audit.previous_transaction_id,
                audit.previous_transfer_id,
            )
        return movement_ids

    @staticmethod
    def _anonymize_audit_copies(movement_ids: set[int]) -> None:
        """Scrub statement-origin values from audit copies of movements.

        Only entries written by an import, resolution or markup operation
        are touched. Independent financial audit entries keep their values.
        """
        if not movement_ids:
            return
        object_ids = {str(pk) for pk in movement_ids}
        entries = AuditLog.objects.filter(
            model_name__in=_STATEMENT_AUDIT_MODELS,
            object_pk__in=object_ids,
            kind__in=_STATEMENT_AUDIT_KINDS,
        )
        for entry in entries:
            scrubbed = _scrub_diff(entry.diff)
            if scrubbed != entry.diff:
                AuditLog.objects.filter(pk=entry.pk).update(diff=scrubbed)

    @staticmethod
    def _record_anonymization(
        upload: BankStatementUpload,
        row_count: int,
        unresolved_count: int,
        cleaned_at: datetime,
    ) -> None:
        """Record cleanup with actor and time, copying no bank values."""
        with audit_operation(kind=AuditOperationKind.STATEMENT_RETENTION):
            AuditLog.objects.create(
                user=upload.user,
                model_name='users.BankStatementUpload',
                object_pk=str(upload.pk),
                object_name='',
                action=AuditLog.Action.DELETE,
                diff={
                    'v': 2,
                    'retention_cleaned_at': {
                        'old': None,
                        'new': cleaned_at.isoformat(),
                    },
                    'rows': row_count,
                    'unresolved': unresolved_count,
                },
                kind=AuditOperationKind.STATEMENT_RETENTION,
            )


def _collect_created_movement(
    movement_ids: set[int],
    decision: str,
    transaction_id: int | None,
    transfer_id: int | None,
) -> None:
    """Add the movement a NEW or TRANSFERRED decision created."""
    if decision not in _CREATED_DECISIONS:
        return
    if transaction_id is not None:
        movement_ids.add(transaction_id)
    if transfer_id is not None:
        movement_ids.add(transfer_id)


def _scrub_diff(diff: Any) -> Any:
    """Remove bank-derived values from one stored audit diff."""
    if not isinstance(diff, dict):
        return diff
    scrubbed: dict[str, Any] = dict(diff)
    for section in ('created', 'deleted'):
        values = scrubbed.get(section)
        if isinstance(values, dict):
            scrubbed[section] = {
                key: value
                for key, value in values.items()
                if key not in _BANK_COPY_FIELDS
            }
    changes = scrubbed.get('changed')
    if isinstance(changes, dict):
        scrubbed['changed'] = {
            key: value
            for key, value in changes.items()
            if key not in _BANK_COPY_FIELDS
        }
    return scrubbed
