"""Data access for automatic receipt processing logs."""

from decimal import Decimal
from typing import Any

from django.db import IntegrityError
from django.db.models import Q, QuerySet
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.receipts.models import (
    Receipt,
    ReceiptImageHash,
    ReceiptProcessingLog,
    ReceiptProcessingStatus,
)
from hasta_la_vista_money.receipts.services.receipt_creator import (
    receipt_balance_delta,
)
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
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
        logs = ReceiptProcessingLog.objects.filter(user=user)
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
        filters: dict[str, Any] = {
            'pk': log.pk,
            'status': ReceiptProcessingStatus.PROCESSING,
        }
        if log.task_id:
            filters['task_id'] = task_id
        try:
            return bool(
                ReceiptProcessingLog.objects.filter(**filters).update(
                    fiscal_key=fiscal_key,
                ),
            )
        except IntegrityError:
            self.mark_duplicate(log=log, task_id=task_id)
            return False

    def mark_failed(
        self,
        *,
        log: ReceiptProcessingLog,
        error_message: str,
        task_id: str,
    ) -> None:
        filters: dict[str, Any] = {
            'pk': log.pk,
            'status': ReceiptProcessingStatus.PROCESSING,
        }
        if log.task_id:
            filters['task_id'] = task_id
        ReceiptProcessingLog.objects.filter(**filters).update(
            status=ReceiptProcessingStatus.FAILED,
            error_message=error_message,
        )

    def mark_duplicate(
        self,
        *,
        log: ReceiptProcessingLog,
        task_id: str,
    ) -> None:
        filters: dict[str, Any] = {'pk': log.pk}
        if log.task_id:
            filters['task_id'] = task_id
        ReceiptProcessingLog.objects.filter(**filters).update(
            status=ReceiptProcessingStatus.DUPLICATE,
            is_duplicate=True,
        )

    def get_for_completion(self, *, log_id: int) -> ReceiptProcessingLog:
        return (
            ReceiptProcessingLog.objects.select_for_update()
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
        log.save(
            update_fields=['image_file', 'receipt', 'status', 'error_message'],
        )

    def reset_for_retry(
        self,
        *,
        log: ReceiptProcessingLog,
    ) -> ReceiptProcessingLog:
        log.status = ReceiptProcessingStatus.PROCESSING
        log.error_message = ''
        log.processing_started_at = timezone.now()
        log.save(
            update_fields=['status', 'error_message', 'processing_started_at'],
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

    def balance_after_receipt(self, *, receipt: Receipt) -> Decimal:
        """Reconstruct the account balance immediately after this receipt."""
        balance = receipt.account.balance
        later_receipts = Receipt.objects.filter(
            account_id=receipt.account_id,
            receipt_date__gt=receipt.receipt_date,
        )
        for later_receipt in later_receipts:
            balance -= receipt_balance_delta(
                later_receipt.operation_type,
                later_receipt.total_sum,
            )
        later_transactions = Transaction.objects.filter(
            account_id=receipt.account_id,
            date__gt=receipt.receipt_date,
        )
        for transaction in later_transactions:
            delta = (
                transaction.amount
                if transaction.type == TransactionType.INCOME
                else -transaction.amount
            )
            balance -= delta
        later_transfers = TransferMoneyLog.objects.filter(
            Q(from_account_id=receipt.account_id)
            | Q(to_account_id=receipt.account_id),
            exchange_date__gt=receipt.receipt_date,
        )
        for transfer in later_transfers:
            delta = Decimal('0.00')
            if transfer.from_account_id == receipt.account_id:
                delta -= transfer.amount
            if transfer.to_account_id == receipt.account_id:
                delta += transfer.amount
            balance -= delta
        return balance
