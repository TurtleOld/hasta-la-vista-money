"""Clean up bank statement details once their retention period ends."""

from datetime import datetime
from functools import partial

import structlog
from django.core.files.storage import Storage
from django.db import transaction
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.services.statement_audit_scrub import (
    scrub_transaction_source_ref_audit,
)
from hasta_la_vista_money.transactions.models import Transaction
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
        # A cleaned generation whose PDF deletion failed keeps its pointer:
        # the next run retries the irreversible storage delete.
        upload_ids.update(
            BankStatementUpload.objects.filter(
                retention_cleaned_at__isnull=False,
            )
            .exclude(pdf_file='')
            .values_list('pk', flat=True),
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
            pending_file_name = (
                upload.pdf_file.name
                if upload.retention_cleaned_at is not None
                and upload.pdf_file.name
                else ''
            )
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
            if not due_rows and not upload_due and not pending_file_name:
                return False

            related_transaction_ids = {
                row.transaction_id
                for row in due_rows
                if row.transaction_id is not None
            }
            if upload_due and upload.file_hash:
                related_transaction_ids.update(
                    Transaction.objects.filter(
                        account_id=account_id,
                        source_file_hash=upload.file_hash,
                    ).values_list('pk', flat=True),
                )

            if due_rows:
                row_ids = [row.pk for row in due_rows]
                BankStatementCandidate.objects.filter(
                    row_id__in=row_ids,
                ).delete()
                BankStatementRow.objects.filter(pk__in=row_ids).update(
                    transaction_type=None,
                    transaction_date=None,
                    bank_calendar_date=None,
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
                upload.retention_cleaned_at = now
                upload.statement_closing_balance = None
                upload.account_balance_after = None
                upload.balance_discrepancy = None
                upload.error_message = ''
                upload.celery_task_id = ''
                upload.save(
                    update_fields=[
                        'retention_cleaned_at',
                        'statement_closing_balance',
                        'account_balance_after',
                        'balance_discrepancy',
                        'error_message',
                        'celery_task_id',
                    ],
                )
                pending_file_name = upload.pdf_file.name
            scrub_transaction_source_ref_audit(related_transaction_ids)
            self.reconciliation_service.refresh_outcome_counts(upload)
            if pending_file_name:
                # The delete is irreversible: it runs only after the DB work
                # above commits, and the pointer stays until it succeeds.
                transaction.on_commit(
                    partial(
                        self._delete_pending_file,
                        upload.pk,
                        pending_file_name,
                        upload.pdf_file.storage,
                    ),
                )
        return bool(due_rows or upload_due)

    @staticmethod
    def _delete_pending_file(
        upload_id: int,
        file_name: str,
        storage: Storage,
    ) -> None:
        """Delete the committed file and only then clear its pointer.

        A storage failure leaves the cleaned pointer in place, so the next
        cleanup retries it. The pointer is cleared only when it still names
        this file and the generation is still cleaned: a reupload that
        replaced it was never touched by this callback.
        """
        try:
            storage.delete(file_name)
        except Exception:
            logger.warning(
                'statement_retention_pdf_delete_failed',
                upload_id=upload_id,
            )
            return
        try:
            with transaction.atomic():
                account_id = (
                    BankStatementUpload.objects.filter(pk=upload_id)
                    .values_list('account_id', flat=True)
                    .first()
                )
                if account_id is None:
                    return
                Account.objects.select_for_update().get(pk=account_id)
                upload = (
                    BankStatementUpload.objects.select_for_update()
                    .filter(pk=upload_id)
                    .first()
                )
                if (
                    upload is None
                    or upload.retention_cleaned_at is None
                    or upload.pdf_file.name != file_name
                ):
                    return
                upload.pdf_file = ''
                upload.save(update_fields=['pdf_file', 'updated_at'])
        except Exception:
            # The file is gone and the pointer stays for the next retry.
            logger.warning(
                'statement_retention_pdf_pointer_clear_failed',
                upload_id=upload_id,
            )
