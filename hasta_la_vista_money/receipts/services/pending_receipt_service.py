from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.repositories.protocols import ReceiptRepositoryProtocol
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import PendingReceipt, Receipt
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    ReceiptCreatorService,
    SellerCreateData,
)
from hasta_la_vista_money.users.models import User


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

    def create_pending_receipt(
        self,
        *,
        user: User,
        account: Account,
        receipt_data: dict[str, Any],
    ) -> PendingReceipt:
        """Create a pending receipt from recognition data.

        Args:
            user: User who uploaded the receipt.
            account: Account to charge for the receipt.
            receipt_data: Dictionary with receipt data from AI recognition.

        Returns:
            Created PendingReceipt instance.
        """
        expires_at = timezone.now() + timedelta(hours=24)
        return PendingReceipt.objects.create(
            user=user,
            account=account,
            receipt_data=receipt_data,
            expires_at=expires_at,
        )

    def update_pending_receipt(
        self,
        *,
        pending_receipt: PendingReceipt,
        receipt_data: dict[str, Any],
    ) -> PendingReceipt:
        """Update pending receipt data.

        Args:
            pending_receipt: PendingReceipt instance to update.
            receipt_data: Updated receipt data dictionary.

        Returns:
            Updated PendingReceipt instance.
        """
        pending_receipt.receipt_data = receipt_data
        pending_receipt.save(update_fields=['receipt_data'])
        return pending_receipt

    @transaction.atomic
    def convert_to_receipt(
        self,
        *,
        pending_receipt: PendingReceipt,
    ) -> Receipt:
        """Convert pending receipt to final Receipt.

        Args:
            pending_receipt: PendingReceipt instance to convert.

        Returns:
            Created Receipt instance.

        Raises:
            ValueError: If receipt data is invalid.
        """
        receipt_data = pending_receipt.receipt_data
        user = pending_receipt.user
        account = pending_receipt.account

        receipt_date_str = receipt_data.get('receipt_date')
        if not receipt_date_str:
            raise ValueError('receipt_date is required')

        receipt_date = self._parse_receipt_date(receipt_date_str)
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
                    receipt_data.get('name_seller', 'Неизвестный продавец'),
                ),
                retail_place_address=receipt_data.get('retail_place_address'),
                retail_place=receipt_data.get('retail_place'),
            ),
            products_data=receipt_data.get('items', []),
        )

        pending_receipt.delete()
        return receipt

    def _parse_receipt_date(self, date_str: str) -> datetime:
        """Parse receipt date string to datetime.

        Args:
            date_str: Date string in DD.MM.YYYY HH:MM format.

        Returns:
            Timezone-aware datetime instance.
        """
        try:
            day, month, year = date_str.split(' ')[0].split('.')
            hour, minute = date_str.split(' ')[1].split(':')
            return datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                tzinfo=timezone.get_current_timezone(),
            )
        except (ValueError, IndexError):
            normalized_date = self._normalize_date(date_str)
            day, month, year = normalized_date.split(' ')[0].split('.')
            hour, minute = normalized_date.split(' ')[1].split(':')
            return datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                tzinfo=timezone.get_current_timezone(),
            )

    def _normalize_date(self, date_str: str) -> str:
        """Normalize date string to standard format.

        Args:
            date_str: Date string in various formats.

        Returns:
            Normalized date string in DD.MM.YYYY HH:MM format.
        """
        try:
            day, month, year = date_str.split(' ')[0].split('.')
            hour, minute = date_str.split(' ')[1].split(':')
            aware_dt = datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                tzinfo=timezone.get_current_timezone(),
            )
            return aware_dt.strftime('%d.%m.%Y %H:%M')
        except ValueError:
            day, month, year_short, time = date_str.replace(' ', '.').split('.')
            current_century = str(timezone.now().year)[:2]
            return f'{day}.{month}.{current_century}{year_short} {time}'

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
