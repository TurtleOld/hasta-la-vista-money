"""Start a bank statement upload without posting on a repeated file.

The view only validates the form and shows the outcome; every lock, storage
and retention decision lives here so the same rules apply to the repeat path,
the API and any future caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

import structlog
from django.db import transaction
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import (
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.repositories.statement_row_repository import (
    StatementRowRepository,
)
from hasta_la_vista_money.users.services.statement_retention_policy import (
    statement_retention_deadline,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

    from hasta_la_vista_money.users.protocols.services import (
        BankStatementRetentionServiceProtocol,
    )

logger = structlog.get_logger(__name__)


class UploadStartStatus(StrEnum):
    """Outcome of asking to store one upload generation."""

    STARTED = 'started'
    REPEATED = 'repeated'
    IN_FLIGHT = 'in_flight'
    CLEANUP_PENDING = 'cleanup_pending'


@dataclass(frozen=True)
class UploadStartResult:
    """What the view needs to react to one upload attempt."""

    status: UploadStartStatus
    upload_id: int
    reconciliation_only: bool


class BankStatementUploadStartService:
    """Store a PDF and, when the file is known, start a reconciliation run."""

    def __init__(
        self,
        retention_service: BankStatementRetentionServiceProtocol,
    ) -> None:
        self._retention_service = retention_service

    def start(
        self,
        *,
        user: User,
        account: Account,
        pdf_file: UploadedFile,
        reconciliation_only: bool,
    ) -> UploadStartResult:
        """Lock the account, store the generation and report what happened.

        A repeated file never posts movements: it only schedules a
        reconciliation-only run. A generation that a live task still owns is
        never replaced.
        """
        file_hash = self._pdf_hash(pdf_file)
        self._retry_retained_pdf_cleanup(user, account, file_hash)
        logger.info(
            'bank_statement_upload_creating',
            user_id=user.pk,
            account_id=account.pk,
        )
        with transaction.atomic():
            # The agreed lock order: the account first, then the upload.
            Account.objects.select_for_update().get(pk=account.pk)
            upload, created = BankStatementUpload.objects.get_or_create(
                user=user,
                account=account,
                file_hash=file_hash,
                defaults={
                    'pdf_file': pdf_file,
                    'status': BankStatementUpload.Status.PENDING,
                    'expires_at': statement_retention_deadline(user),
                    'reconciliation_only': reconciliation_only,
                },
            )
            if created:
                status = UploadStartStatus.STARTED
            else:
                upload = BankStatementUpload.objects.select_for_update().get(
                    pk=upload.pk,
                )
                if self._is_fresh_in_flight(upload):
                    return UploadStartResult(
                        status=UploadStartStatus.IN_FLIGHT,
                        upload_id=upload.pk,
                        reconciliation_only=True,
                    )
                if not self._replace_generation(upload, user, pdf_file):
                    return UploadStartResult(
                        status=UploadStartStatus.CLEANUP_PENDING,
                        upload_id=upload.pk,
                        reconciliation_only=True,
                    )
                status = UploadStartStatus.REPEATED
                reconciliation_only = True
        logger.info(
            'bank_statement_upload_created',
            upload_id=upload.pk,
            user_id=user.pk,
            repeated=status is UploadStartStatus.REPEATED,
        )
        return UploadStartResult(
            status=status,
            upload_id=upload.pk,
            reconciliation_only=reconciliation_only,
        )

    def _replace_generation(
        self,
        upload: BankStatementUpload,
        user: User,
        pdf_file: UploadedFile,
    ) -> bool:
        """Replace a known generation; ``False`` when its PDF is still there."""
        retention_marker = upload.retention_cleaned_at
        if retention_marker is not None:
            if upload.pdf_file.name:
                # The irreversible delete did not finish: never point the row
                # at a new file while the old one is still stored.
                return False
            StatementRowRepository.stamp_legacy_cleaned_rows(
                upload.pk,
                retention_marker,
            )
        old_pdf_name = upload.pdf_file.name
        storage = upload.pdf_file.storage
        upload.pdf_file = pdf_file
        upload.expires_at = statement_retention_deadline(user)
        upload.retention_cleaned_at = None
        upload.reconciliation_only = True
        upload.status = BankStatementUpload.Status.PENDING
        upload.progress = 0
        upload.processed_transactions = 0
        upload.error_message = ''
        upload.celery_task_id = ''
        upload.save(
            update_fields=[
                'pdf_file',
                'expires_at',
                'retention_cleaned_at',
                'reconciliation_only',
                'status',
                'progress',
                'processed_transactions',
                'error_message',
                'celery_task_id',
                'updated_at',
            ],
        )
        if old_pdf_name and old_pdf_name != upload.pdf_file.name:
            transaction.on_commit(lambda: storage.delete(old_pdf_name))
        return True

    def _retry_retained_pdf_cleanup(
        self,
        user: User,
        account: Account,
        file_hash: str,
    ) -> None:
        """Retry a retained PDF delete before replacing its pointer."""
        has_pending_pdf = (
            BankStatementUpload.objects.filter(
                user=user,
                account=account,
                file_hash=file_hash,
                retention_cleaned_at__isnull=False,
            )
            .exclude(pdf_file='')
            .exists()
        )
        if has_pending_pdf:
            self._retention_service.cleanup_expired()

    @staticmethod
    def _is_fresh_in_flight(upload: BankStatementUpload) -> bool:
        """Tell whether a live run still owns this upload generation."""
        if upload.status not in {
            BankStatementUpload.Status.PENDING,
            BankStatementUpload.Status.PROCESSING,
        }:
            return False
        stale_after = timedelta(
            minutes=constants.STATEMENT_UPLOAD_STALE_MINUTES,
        )
        return timezone.now() - upload.updated_at <= stale_after

    @staticmethod
    def _pdf_hash(pdf_file: UploadedFile) -> str:
        """Hash an uploaded PDF while restoring its read position."""
        digest = sha256()
        for chunk in pdf_file.chunks():
            digest.update(chunk)
        pdf_file.seek(0)
        return digest.hexdigest()


__all__ = [
    'BankStatementUploadStartService',
    'UploadStartResult',
    'UploadStartStatus',
]
