"""Clean up bank statement details once their retention period ends."""

from datetime import datetime

import structlog
from django.db import transaction
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementRow,
    BankStatementUpload,
)
from hasta_la_vista_money.users.protocols.services import (
    BankStatementReconciliationServiceProtocol,
)
from hasta_la_vista_money.users.repositories.statement_row_repository import (
    StatementRowRepository,
)
from hasta_la_vista_money.users.services.statement_retention_policy import (
    row_data_due,
    upload_generation_due,
)

logger = structlog.get_logger(__name__)


class BankStatementRetentionService:
    """Expire statement reconciliations and remove retained bank data."""

    def __init__(
        self,
        reconciliation_service: BankStatementReconciliationServiceProtocol,
    ) -> None:
        """Initialize retention with the reconciliation counter service."""
        self.reconciliation_service = reconciliation_service

    def cleanup_expired(self, now: datetime | None = None) -> int:
        """Clean upload generations and rows whose own deadline passed."""
        deadline = now or timezone.now()
        upload_ids = set(
            BankStatementUpload.objects.filter(
                expires_at__lte=deadline,
                retention_cleaned_at__isnull=True,
            ).values_list('pk', flat=True),
        )
        upload_ids.update(
            BankStatementRow.objects.filter(
                StatementRowRepository.bank_data_due_q(deadline),
            ).values_list('upload_id', flat=True),
        )
        cleaned = 0
        for upload_id in sorted(upload_ids):
            if self._cleanup_upload(upload_id, deadline):
                cleaned += 1
        return cleaned

    def _cleanup_upload(self, upload_id: int, now: datetime) -> bool:
        """Clean one upload under the account, upload, row lock order.

        The upload and row deadlines are read again behind the lock. Only
        rows due at that moment lose their details; an explicit row deadline
        wins over the upload generation, and an already-cleaned upload keeps
        its restored rows until their own deadline. PDF and bank sums are
        removed only for an expired, not-yet-cleaned upload generation.
        Unconverted raw bank identifiers block the cleanup of due rows:
        dropping them would lose duplicate protection before conversion.
        """
        with transaction.atomic():
            account_id = (
                BankStatementUpload.objects.filter(pk=upload_id)
                .values_list('account_id', flat=True)
                .first()
            )
            if account_id is None:
                return False
            Account.objects.select_for_update().get(pk=account_id)
            upload = BankStatementUpload.objects.select_for_update().get(
                pk=upload_id,
            )
            rows = list(
                BankStatementRow.objects.select_for_update().filter(
                    upload=upload,
                ),
            )
            upload_due = upload_generation_due(upload, now)
            due_rows = [
                row
                for row in rows
                if row_data_due(row, upload_due=upload_due, now=now)
            ]
            if any(
                row.source_ref and not row.source_ref_hash for row in due_rows
            ):
                logger.warning(
                    'statement_retention_raw_source_ref_unconverted',
                    upload_id=upload_id,
                )
                return False
            if not due_rows and not upload_due:
                return False

            if due_rows:
                row_ids = [row.pk for row in due_rows]
                BankStatementCandidate.objects.filter(
                    row_id__in=row_ids,
                ).delete()
                BankStatementRow.objects.filter(pk__in=row_ids).update(
                    transaction_type=None,
                    transaction_date=None,
                    amount=None,
                    description='',
                    candidate_description='',
                    suggested_category='',
                    merchant_key='',
                    counterparty_account='',
                    kind='',
                    source_ref=None,
                    candidate=None,
                    data_cleaned_at=now,
                )
            if upload_due:
                file_name = upload.pdf_file.name
                if file_name:
                    upload.pdf_file.storage.delete(file_name)
                upload.pdf_file = ''
                upload.retention_cleaned_at = now
                upload.statement_closing_balance = None
                upload.account_balance_after = None
                upload.balance_discrepancy = None
                upload.error_message = ''
                upload.celery_task_id = ''
                upload.save(
                    update_fields=[
                        'pdf_file',
                        'retention_cleaned_at',
                        'statement_closing_balance',
                        'account_balance_after',
                        'balance_discrepancy',
                        'error_message',
                        'celery_task_id',
                    ],
                )
            self.reconciliation_service.refresh_outcome_counts(upload)
        return True
