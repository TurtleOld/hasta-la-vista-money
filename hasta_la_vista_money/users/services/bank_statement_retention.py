from datetime import datetime

from django.db import transaction
from django.utils import timezone

from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementRow,
    BankStatementUpload,
)
from hasta_la_vista_money.users.protocols.services import (
    BankStatementReconciliationServiceProtocol,
)


class BankStatementRetentionService:
    """Expire statement reconciliations and remove retained bank data."""

    def __init__(
        self,
        reconciliation_service: BankStatementReconciliationServiceProtocol,
    ) -> None:
        """Initialize retention with the reconciliation counter service."""
        self.reconciliation_service = reconciliation_service

    def cleanup_expired(self, now: datetime | None = None) -> int:
        """Clean every expired upload once and return the cleaned count."""
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
        upload = BankStatementUpload.objects.filter(pk=upload_id).first()
        if upload is None or upload.retention_cleaned_at is not None:
            return False
        file_name = upload.pdf_file.name
        if file_name:
            upload.pdf_file.storage.delete(file_name)

        with transaction.atomic():
            upload = BankStatementUpload.objects.select_for_update().get(
                pk=upload_id,
            )
            if (
                upload.retention_cleaned_at is not None
                or upload.expires_at > now
            ):
                return False
            rows = list(
                BankStatementRow.objects.select_for_update().filter(
                    upload=upload,
                ),
            )
            unresolved = [
                row
                for row in rows
                if row.decision == BankStatementRow.Decision.PENDING
            ]
            unresolved_ids = [row.pk for row in unresolved]
            if unresolved_ids:
                BankStatementRow.objects.filter(
                    pk__in=unresolved_ids,
                ).update(
                    decision=BankStatementRow.Decision.EXPIRED,
                    decided_at=now,
                )
            row_ids = [row.pk for row in rows]
            BankStatementCandidate.objects.filter(row_id__in=row_ids).delete()
            BankStatementRow.objects.filter(pk__in=row_ids).update(
                transaction_type=None,
                transaction_date=None,
                amount=None,
                description='',
                candidate_description='',
                suggested_category='',
                source_ref=None,
                source_row_position=None,
                candidate=None,
            )
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
            self.reconciliation_service.refresh_outcome_counts(upload)
        return True
