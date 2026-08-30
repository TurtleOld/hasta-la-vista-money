"""Automatic receipt processing backed by an audit log."""

import hashlib
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Receipt,
    ReceiptProcessingLog,
    ReceiptProcessingStatus,
)
from hasta_la_vista_money.receipts.parsers.date_parser import ReceiptDateParser
from hasta_la_vista_money.receipts.protocols.services import (
    ReceiptCreatorServiceProtocol,
)
from hasta_la_vista_money.receipts.repositories.receipt_processing_log_repository import (  # noqa: E501
    ReceiptProcessingLogRepository,
)
from hasta_la_vista_money.receipts.services.receipt_adjustment import (
    calculate_receipt_adjustment,
)
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    SellerCreateData,
)
from hasta_la_vista_money.users.models import User

_HASH_CHUNK_SIZE = 64 * 1024


def compute_image_hash(file_obj: Any) -> str:
    """Return the SHA-256 digest of an uploaded image without consuming it."""
    digest = hashlib.sha256()
    if hasattr(file_obj, 'chunks'):
        for chunk in file_obj.chunks(chunk_size=_HASH_CHUNK_SIZE):
            digest.update(chunk)
    else:
        while chunk := file_obj.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    return digest.hexdigest()


class ReceiptProcessingService:
    """Creates and completes durable automatic processing attempts."""

    def __init__(
        self,
        receipt_creator_service: ReceiptCreatorServiceProtocol,
        processing_log_repository: ReceiptProcessingLogRepository,
    ) -> None:
        self.receipt_creator_service = receipt_creator_service
        self.processing_log_repository = processing_log_repository

    def find_duplicate(
        self,
        *,
        user: User,
        image_hash: str | None = None,
        fiscal_key: str | None = None,
    ) -> Receipt | ReceiptProcessingLog | None:
        return self.processing_log_repository.find_duplicate(
            user=user,
            image_hash=image_hash,
            fiscal_key=fiscal_key,
        )

    def create_image_job(
        self,
        *,
        user: User,
        account: Account,
        image_file: Any,
        image_hash: str,
    ) -> ReceiptProcessingLog:
        return self.processing_log_repository.create_image_job(
            user=user,
            account=account,
            image_file=image_file,
            image_hash=image_hash,
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
        return self.processing_log_repository.create_qr_job(
            user=user,
            account=account,
            qr_raw=qr_raw,
            image_hash=image_hash,
            fiscal_key=fiscal_key,
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
        return self.processing_log_repository.create_duplicate_qr_job(
            user=user,
            account=account,
            qr_raw=qr_raw,
            image_hash=image_hash,
            fiscal_key=fiscal_key,
        )

    def attach_task_id(
        self,
        *,
        log: ReceiptProcessingLog,
        task_id: str,
    ) -> None:
        self.processing_log_repository.attach_task_id(log=log, task_id=task_id)

    def claim_fiscal_key(
        self,
        *,
        log: ReceiptProcessingLog,
        fiscal_key: str,
        task_id: str,
    ) -> bool:
        return self.processing_log_repository.claim_fiscal_key(
            log=log,
            fiscal_key=fiscal_key,
            task_id=task_id,
        )

    def mark_failed(
        self,
        *,
        log: ReceiptProcessingLog,
        error_message: str,
        task_id: str,
    ) -> None:
        self.processing_log_repository.mark_failed(
            log=log,
            error_message=error_message,
            task_id=task_id,
        )

    def mark_duplicate(
        self,
        *,
        log: ReceiptProcessingLog,
        task_id: str,
    ) -> None:
        self.processing_log_repository.mark_duplicate(
            log=log,
            task_id=task_id,
        )

    @transaction.atomic
    def complete(
        self,
        *,
        log: ReceiptProcessingLog,
        receipt_data: dict[str, Any],
        task_id: str,
    ) -> Receipt:
        log = self.processing_log_repository.get_for_completion(log_id=log.pk)
        if log.receipt is not None:
            return log.receipt
        if log.status != ReceiptProcessingStatus.PROCESSING:
            raise ValueError('Receipt processing log is not active')
        if log.task_id and log.task_id != task_id:
            raise ValueError('Receipt processing task is stale')

        total_sum = Decimal(str(receipt_data['total_sum']))
        adjustment = calculate_receipt_adjustment(
            total_sum,
            receipt_data.get('items', []),
        )
        receipt = self.receipt_creator_service.create_receipt_with_products(
            user=log.user,
            account=log.account,
            receipt_data=ReceiptCreateData(
                receipt_date=ReceiptDateParser.parse(
                    receipt_data['receipt_date'],
                ),
                total_sum=total_sum,
                number_receipt=receipt_data.get('number_receipt'),
                nds10=self._decimal_or_none(receipt_data.get('nds10')),
                nds20=self._decimal_or_none(receipt_data.get('nds20')),
                operation_type=receipt_data.get('operation_type', 0),
                adjustment=adjustment,
                fiscal_key=log.fiscal_key,
            ),
            seller_data=SellerCreateData(
                name_seller=str(
                    receipt_data.get('name_seller', _('Неизвестный продавец')),
                ),
                retail_place_address=receipt_data.get('retail_place_address'),
                retail_place=receipt_data.get('retail_place'),
                inn=receipt_data.get('inn'),
            ),
            products_data=receipt_data.get('items', []),
            requires_attention=adjustment != 0,
            attention_reason=(
                str(constants.RECEIPT_ATTENTION_REASON_TOTAL_MISMATCH)
                if adjustment != 0
                else ''
            ),
            allow_insufficient_funds=True,
        )
        self.processing_log_repository.complete(log=log, receipt=receipt)
        return receipt

    def reset_for_retry(
        self,
        *,
        log: ReceiptProcessingLog,
    ) -> ReceiptProcessingLog:
        return self.processing_log_repository.reset_for_retry(log=log)

    def get_for_user(
        self,
        *,
        user: User,
        log_id: int,
    ) -> ReceiptProcessingLog | None:
        return self.processing_log_repository.get_for_user(
            user=user,
            log_id=log_id,
        )

    def get_visible_for_user(self, *, user: User) -> Any:
        return self.processing_log_repository.get_visible_for_user(user=user)

    def get_unnotified_completed(
        self,
        *,
        user: User,
    ) -> list[ReceiptProcessingLog]:
        return self.processing_log_repository.get_unnotified_completed(
            user=user,
        )

    def is_insufficient_at_conducting(self, *, receipt: Receipt) -> bool:
        return (
            self.processing_log_repository.balance_after_receipt(
                receipt=receipt,
            )
            < 0
        )

    @staticmethod
    def _decimal_or_none(value: Any) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None
