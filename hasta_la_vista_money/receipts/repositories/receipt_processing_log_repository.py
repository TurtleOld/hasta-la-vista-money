"""Data access for automatic receipt processing logs."""

from collections.abc import Collection
from functools import partial
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.db.models.fields.files import FieldFile
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Receipt,
    ReceiptImageHash,
    ReceiptProcessingErrorCode,
    ReceiptProcessingLog,
    ReceiptProcessingStage,
    ReceiptProcessingStatus,
)
from hasta_la_vista_money.users.models import User


class ReceiptProcessingLogRepository:
    """Persist and query automatic receipt processing attempts."""

    def find_duplicate(
        self,
        *,
        user: User,
        image_hash: str | None = None,
        fiscal_key: str | None = None,
    ) -> Receipt | ReceiptProcessingLog | None:
        if fiscal_key:
            receipt = Receipt.objects.filter(
                user=user,
                fiscal_key=fiscal_key,
            ).first()
            if receipt is not None:
                return receipt
        logs = ReceiptProcessingLog.objects.filter(user=user).exclude(
            status=ReceiptProcessingStatus.FAILED,
        )
        if fiscal_key:
            log = logs.filter(fiscal_key=fiscal_key).first()
            if log is not None:
                return log
        if image_hash:
            log = logs.filter(image_hash=image_hash).first()
            if log is not None:
                return log
            hash_record = (
                ReceiptImageHash.objects.filter(
                    user=user,
                    image_hash=image_hash,
                )
                .select_related('receipt')
                .first()
            )
            if hash_record is not None:
                return hash_record.receipt
        return None

    def create_image_job(
        self,
        *,
        user: User,
        account: Account,
        image_file: Any,
        image_hash: str,
    ) -> ReceiptProcessingLog:
        return ReceiptProcessingLog.objects.create(
            user=user,
            account=account,
            image_file=image_file,
            image_hash=image_hash,
            processing_started_at=timezone.now(),
        )

    def create_qr_job(
        self,
        *,
        user: User,
        account: Account,
        qr_raw: str,
        image_hash: str,
        fiscal_key: str,
    ) -> ReceiptProcessingLog:
        return ReceiptProcessingLog.objects.create(
            user=user,
            account=account,
            qr_raw=qr_raw,
            image_hash=image_hash,
            fiscal_key=fiscal_key,
            processing_started_at=timezone.now(),
        )

    def create_duplicate_qr_job(
        self,
        *,
        user: User,
        account: Account,
        qr_raw: str,
        image_hash: str,
        fiscal_key: str,
    ) -> ReceiptProcessingLog:
        return ReceiptProcessingLog.objects.create(
            user=user,
            account=account,
            status=ReceiptProcessingStatus.DUPLICATE,
            qr_raw=qr_raw,
            image_hash=image_hash,
            fiscal_key=fiscal_key,
            is_duplicate=True,
            processing_started_at=timezone.now(),
        )

    def attach_task_id(
        self,
        *,
        log: ReceiptProcessingLog,
        task_id: str,
    ) -> None:
        ReceiptProcessingLog.objects.filter(pk=log.pk).update(task_id=task_id)
        log.task_id = task_id

    def claim_fiscal_key(
        self,
        *,
        log: ReceiptProcessingLog,
        fiscal_key: str,
        task_id: str,
    ) -> bool:
        if Receipt.objects.filter(
            user_id=log.user_id,
            fiscal_key=fiscal_key,
        ).exists():
            self.mark_duplicate(log=log, task_id=task_id)
            return False
        try:
            claimed = bool(
                self._owned(log=log, task_id=task_id)
                .filter(status=ReceiptProcessingStatus.PROCESSING)
                .update(fiscal_key=fiscal_key),
            )
        except IntegrityError:
            self.mark_duplicate(log=log, task_id=task_id)
            return False
        if claimed:
            log.fiscal_key = fiscal_key
        return claimed

    def mark_failed(
        self,
        *,
        log: ReceiptProcessingLog,
        error_code: ReceiptProcessingErrorCode,
        error_stage: ReceiptProcessingStage | None,
        error_message: str,
        task_id: str,
    ) -> bool:
        return bool(
            self._owned(log=log, task_id=task_id)
            .filter(status=ReceiptProcessingStatus.PROCESSING)
            .update(
                status=ReceiptProcessingStatus.FAILED,
                error_code=error_code,
                error_stage=error_stage or '',
                error_message=error_message,
            ),
        )

    def record_retry(
        self,
        *,
        log: ReceiptProcessingLog,
        error_code: ReceiptProcessingErrorCode,
        error_stage: ReceiptProcessingStage | None,
        task_id: str,
    ) -> bool:
        return bool(
            self._owned(log=log, task_id=task_id)
            .filter(status=ReceiptProcessingStatus.PROCESSING)
            .update(error_code=error_code, error_stage=error_stage or ''),
        )

    def mark_duplicate(
        self,
        *,
        log: ReceiptProcessingLog,
        task_id: str,
    ) -> bool:
        return bool(
            self._owned(log=log, task_id=task_id).update(
                status=ReceiptProcessingStatus.DUPLICATE,
                is_duplicate=True,
            ),
        )

    def delete_in_status(
        self,
        *,
        log: ReceiptProcessingLog,
        statuses: Collection[ReceiptProcessingStatus],
    ) -> bool:
        deleted, _ = ReceiptProcessingLog.objects.filter(
            pk=log.pk,
            status__in=statuses,
        ).delete()
        if deleted:
            self._delete_image_on_commit(log.image_file)
        return bool(deleted)

    def delete_failed(
        self,
        *,
        user: User,
        image_hash: str | None = None,
        fiscal_key: str | None = None,
        exclude: ReceiptProcessingLog | None = None,
    ) -> None:
        lookup = Q()
        if image_hash:
            lookup |= Q(image_hash=image_hash)
        if fiscal_key:
            lookup |= Q(fiscal_key=fiscal_key)
        if not lookup:
            return
        failed = ReceiptProcessingLog.objects.filter(
            lookup,
            user=user,
            status=ReceiptProcessingStatus.FAILED,
        )
        if exclude is not None:
            failed = failed.exclude(pk=exclude.pk)
        images = [log.image_file for log in failed]
        failed.delete()
        for image in images:
            self._delete_image_on_commit(image)

    @staticmethod
    def _delete_image_on_commit(image: FieldFile | None) -> None:
        if image and image.name:
            transaction.on_commit(partial(image.storage.delete, image.name))

    @staticmethod
    def _owned(
        *,
        log: ReceiptProcessingLog,
        task_id: str,
    ) -> QuerySet[ReceiptProcessingLog]:
        filters: dict[str, Any] = {'pk': log.pk}
        if log.task_id:
            filters['task_id'] = task_id
        return ReceiptProcessingLog.objects.filter(**filters)

    def get_for_completion(self, *, log_id: int) -> ReceiptProcessingLog:
        return (
            ReceiptProcessingLog.objects.select_for_update(of=('self',))
            .select_related('user', 'account', 'receipt')
            .get(pk=log_id)
        )

    def complete(self, *, log: ReceiptProcessingLog, receipt: Receipt) -> None:
        if log.image_hash:
            ReceiptImageHash.objects.update_or_create(
                user=log.user,
                image_hash=log.image_hash,
                defaults={'receipt': receipt},
            )
        if log.image_file and log.image_file.name:
            log.image_file.delete(save=False)
        log.image_file = None
        log.receipt = receipt
        log.status = ReceiptProcessingStatus.COMPLETED
        log.error_message = ''
        log.error_code = ''
        log.error_stage = ''
        log.save(
            update_fields=[
                'image_file',
                'receipt',
                'status',
                'error_message',
                'error_code',
                'error_stage',
            ],
        )

    def reset_for_retry(
        self,
        *,
        log: ReceiptProcessingLog,
    ) -> ReceiptProcessingLog:
        log.status = ReceiptProcessingStatus.PROCESSING
        log.error_message = ''
        log.error_code = ''
        log.error_stage = ''
        log.processing_started_at = timezone.now()
        log.save(
            update_fields=[
                'status',
                'error_message',
                'error_code',
                'error_stage',
                'processing_started_at',
            ],
        )
        return log

    def get_for_user(
        self,
        *,
        user: User,
        log_id: int,
    ) -> ReceiptProcessingLog | None:
        return ReceiptProcessingLog.objects.filter(pk=log_id, user=user).first()

    def get_visible_for_user(
        self,
        *,
        user: User,
    ) -> QuerySet[ReceiptProcessingLog]:
        return (
            ReceiptProcessingLog.objects.filter(
                user=user,
                status__in=[
                    ReceiptProcessingStatus.PROCESSING,
                    ReceiptProcessingStatus.FAILED,
                    ReceiptProcessingStatus.DUPLICATE,
                ],
            )
            .select_related('account')
            .order_by('-created_at')
        )

    def get_unnotified_completed(
        self,
        *,
        user: User,
    ) -> list[ReceiptProcessingLog]:
        logs = list(
            ReceiptProcessingLog.objects.filter(
                user=user,
                status=ReceiptProcessingStatus.COMPLETED,
                notified_at__isnull=True,
                receipt__isnull=False,
            ).select_related('receipt')[:5],
        )
        if logs:
            ReceiptProcessingLog.objects.filter(
                pk__in=[log.pk for log in logs],
            ).update(notified_at=timezone.now())
        return logs
