import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from core.repositories.protocols import ReceiptRepositoryProtocol
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    PendingReceiptStatus,
    Receipt,
    ReceiptImageHash,
)
from hasta_la_vista_money.receipts.parsers.date_parser import ReceiptDateParser
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    ReceiptCreatorService,
    SellerCreateData,
)
from hasta_la_vista_money.users.models import User

_HASH_CHUNK_SIZE = 64 * 1024
_TOTAL_WARNING_RATIO = Decimal(
    str(constants.PENDING_RECEIPT_TOTAL_WARNING_RATIO),
)


@dataclass(frozen=True)
class DuplicateImageMatch:
    """Result describing where a duplicate upload was found.

    Attributes:
        kind: ``'pending'`` if matched a PendingReceipt, ``'receipt'`` if a
            saved Receipt was matched via ReceiptImageHash.
        pending: Matched PendingReceipt instance, when ``kind == 'pending'``.
        receipt: Matched Receipt instance, when ``kind == 'receipt'``.
    """

    kind: str
    pending: PendingReceipt | None = None
    receipt: Receipt | None = None


def compute_image_hash(file_obj: Any) -> str:
    """Compute SHA-256 hex digest of an uploaded file in streaming mode.

    Args:
        file_obj: Django UploadedFile or any object with ``chunks`` /
            ``read`` and ``seek`` interface.

    Returns:
        Lowercase 64-char hex digest of the file contents.
    """
    digest = hashlib.sha256()
    if hasattr(file_obj, 'chunks'):
        for chunk in file_obj.chunks(chunk_size=_HASH_CHUNK_SIZE):
            digest.update(chunk)
    else:
        while True:
            chunk = file_obj.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    return digest.hexdigest()


class PendingReceiptService:
    """Service for managing pending receipts before final confirmation."""

    def __init__(
        self,
        receipt_creator_service: ReceiptCreatorService,
        receipt_repository: ReceiptRepositoryProtocol,
    ) -> None:
        """Initialize PendingReceiptService.

        Args:
            receipt_creator_service: Service for creating receipts.
            receipt_repository: Repository for receipt data access.
        """
        self.receipt_creator_service = receipt_creator_service
        self.receipt_repository = receipt_repository

    def find_duplicate(
        self,
        *,
        user: User,
        image_hash: str,
    ) -> DuplicateImageMatch | None:
        """Locate an existing pending or saved receipt for the same image.

        Looks at PendingReceipts in non-failed states (failed entries do not
        block re-uploading, by design) and at the persistent ReceiptImageHash
        records for finalized receipts.

        Args:
            user: User attempting the upload.
            image_hash: SHA-256 hex digest of the uploaded image.

        Returns:
            DuplicateImageMatch describing the match, or None.
        """
        active_statuses = [
            PendingReceiptStatus.PROCESSING,
            PendingReceiptStatus.READY,
            PendingReceiptStatus.READY_WITH_WARNING,
        ]
        pending = (
            PendingReceipt.objects.filter(
                user=user,
                image_hash=image_hash,
                status__in=active_statuses,
            )
            .order_by('-created_at')
            .first()
        )
        if pending is not None:
            return DuplicateImageMatch(kind='pending', pending=pending)

        hash_record = (
            ReceiptImageHash.objects.filter(user=user, image_hash=image_hash)
            .select_related('receipt')
            .first()
        )
        if hash_record is not None:
            return DuplicateImageMatch(
                kind='receipt',
                receipt=hash_record.receipt,
            )
        return None

    def create_processing_job(
        self,
        *,
        user: User,
        account: Account,
        image_file: Any,
        image_hash: str,
    ) -> PendingReceipt:
        """Persist a new PendingReceipt in ``processing`` state with the file.

        Args:
            user: Owner of the receipt.
            account: Account that will be charged for the receipt.
            image_file: Uploaded image file.
            image_hash: Pre-computed SHA-256 hex digest of the file.

        Returns:
            Newly created PendingReceipt.
        """
        return PendingReceipt.objects.create(
            user=user,
            account=account,
            status=PendingReceiptStatus.PROCESSING,
            image_file=image_file,
            image_hash=image_hash,
        )

    def attach_task_id(
        self,
        *,
        pending_receipt: PendingReceipt,
        task_id: str,
    ) -> None:
        """Persist the Celery task identifier on the pending receipt.

        Args:
            pending_receipt: Pending receipt being processed.
            task_id: Celery task UUID.
        """
        pending_receipt.task_id = task_id
        pending_receipt.save(update_fields=['task_id'])

    def mark_ready(
        self,
        *,
        pending_receipt: PendingReceipt,
        receipt_data: dict[str, Any],
    ) -> PendingReceipt:
        """Transition a pending receipt to ``ready`` with parsed data.

        Args:
            pending_receipt: Pending receipt being updated.
            receipt_data: Parsed receipt data dictionary.

        Returns:
            Updated PendingReceipt instance.
        """
        pending_receipt.receipt_data = receipt_data
        pending_receipt.status = self._status_for_receipt_data(receipt_data)
        pending_receipt.error_message = ''
        pending_receipt.save(
            update_fields=['receipt_data', 'status', 'error_message'],
        )
        return pending_receipt

    def mark_failed(
        self,
        *,
        pending_receipt: PendingReceipt,
        error_message: str,
    ) -> PendingReceipt:
        """Transition a pending receipt to ``failed`` with a reason.

        Args:
            pending_receipt: Pending receipt being updated.
            error_message: Human-readable failure reason.

        Returns:
            Updated PendingReceipt instance.
        """
        pending_receipt.status = PendingReceiptStatus.FAILED
        pending_receipt.error_message = error_message
        pending_receipt.save(update_fields=['status', 'error_message'])
        return pending_receipt

    def reset_for_retry(
        self,
        *,
        pending_receipt: PendingReceipt,
    ) -> PendingReceipt:
        """Move a failed pending receipt back to ``processing`` state.

        Args:
            pending_receipt: Failed pending receipt to retry.

        Returns:
            Updated PendingReceipt instance.
        """
        pending_receipt.status = PendingReceiptStatus.PROCESSING
        pending_receipt.error_message = ''
        pending_receipt.save(update_fields=['status', 'error_message'])
        return pending_receipt

    def update_pending_receipt(
        self,
        *,
        pending_receipt: PendingReceipt,
        receipt_data: dict[str, Any],
        account: Account | None = None,
    ) -> PendingReceipt:
        """Update receipt_data on a ready pending receipt during review.

        Args:
            pending_receipt: PendingReceipt instance to update.
            receipt_data: Updated receipt data dictionary.
            account: Account selected for final receipt saving.

        Returns:
            Updated PendingReceipt instance.
        """
        pending_receipt.receipt_data = receipt_data
        pending_receipt.status = self._status_for_receipt_data(receipt_data)
        update_fields = ['receipt_data', 'status']
        if account is not None:
            pending_receipt.account = account
            update_fields.append('account')
        pending_receipt.save(update_fields=update_fields)
        return pending_receipt

    def create_pending_receipt(
        self,
        *,
        user: User,
        account: Account,
        receipt_data: dict[str, Any],
    ) -> PendingReceipt:
        """Create a ready pending receipt directly from recognized data.

        Kept for backward compatibility with callers that already have parsed
        data (e.g. tests). Status is set to ``ready``.

        Args:
            user: User who uploaded the receipt.
            account: Account to charge for the receipt.
            receipt_data: Dictionary with receipt data from AI recognition.

        Returns:
            Created PendingReceipt instance.
        """
        return PendingReceipt.objects.create(
            user=user,
            account=account,
            receipt_data=receipt_data,
            status=self._status_for_receipt_data(receipt_data),
        )

    @transaction.atomic
    def convert_to_receipt(
        self,
        *,
        pending_receipt: PendingReceipt,
    ) -> Receipt:
        """Convert pending receipt to final Receipt and persist its image hash.

        Args:
            pending_receipt: PendingReceipt instance to convert.

        Returns:
            Created Receipt instance.

        Raises:
            ValueError: If receipt data is invalid.
        """
        receipt_data = pending_receipt.receipt_data or {}
        user = pending_receipt.user
        account = pending_receipt.account

        receipt_date_str = receipt_data.get('receipt_date')
        if not receipt_date_str:
            raise ValueError('receipt_date is required')

        receipt_date = ReceiptDateParser.parse(receipt_date_str)
        total_sum = Decimal(str(receipt_data.get('total_sum', 0)))

        receipt = self.receipt_creator_service.create_receipt_with_products(
            user=user,
            account=account,
            receipt_data=ReceiptCreateData(
                receipt_date=receipt_date,
                total_sum=total_sum,
                number_receipt=receipt_data.get('number_receipt'),
                nds10=self._convert_to_optional_decimal(
                    receipt_data.get('nds10'),
                ),
                nds20=self._convert_to_optional_decimal(
                    receipt_data.get('nds20'),
                ),
                operation_type=receipt_data.get('operation_type', 0),
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
        )

        if pending_receipt.image_hash:
            ReceiptImageHash.objects.update_or_create(
                user=user,
                image_hash=pending_receipt.image_hash,
                defaults={'receipt': receipt},
            )

        self.delete_with_file(pending_receipt=pending_receipt)
        return receipt

    def delete_with_file(self, *, pending_receipt: PendingReceipt) -> None:
        """Delete pending receipt and remove the underlying image from disk.

        Args:
            pending_receipt: Pending receipt to delete.
        """
        image_field = pending_receipt.image_file
        if image_field and image_field.name:
            image_field.delete(save=False)
        pending_receipt.delete()

    def _convert_to_optional_decimal(
        self,
        value: str | float | None,
    ) -> Decimal | None:
        """Convert value to Decimal or return None.

        Args:
            value: Value to convert, may be None.

        Returns:
            Decimal instance or None.
        """
        if value is None:
            return None
        return Decimal(str(value))

    def _status_for_receipt_data(
        self,
        receipt_data: dict[str, Any],
    ) -> PendingReceiptStatus:
        if self._has_total_sum_warning(receipt_data):
            return PendingReceiptStatus.READY_WITH_WARNING
        return PendingReceiptStatus.READY

    def _has_total_sum_warning(self, receipt_data: dict[str, Any]) -> bool:
        try:
            total_sum = self._parse_decimal(receipt_data.get('total_sum'))
            items = receipt_data.get('items', [])
            if not isinstance(items, list):
                return False
            items_total = sum(
                (
                    self._parse_decimal(item.get('amount'))
                    for item in items
                    if isinstance(item, dict)
                ),
                Decimal(0),
            )
        except (InvalidOperation, TypeError, ValueError):
            return False

        if total_sum <= 0 or items_total <= 0:
            return False
        return abs(total_sum - items_total) > total_sum * _TOTAL_WARNING_RATIO

    def _parse_decimal(self, value: Any) -> Decimal:
        if isinstance(value, bool) or value is None:
            raise ValueError
        return Decimal(str(value).replace(',', '.').replace(' ', ''))


__all__ = [
    'DuplicateImageMatch',
    'PendingReceiptService',
    'compute_image_hash',
]
