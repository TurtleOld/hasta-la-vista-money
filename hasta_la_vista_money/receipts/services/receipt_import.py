import inspect
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from core.repositories.protocols import ReceiptRepositoryProtocol
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts import services as receipts_services
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    ReceiptCreatorService,
    SellerCreateData,
)
from hasta_la_vista_money.users.models import User

MIN_FUNCTION_PARAMS_COUNT = 2


@dataclass
class ReceiptImportResult:
    """Result of receipt import operation.

    Attributes:
        success: Whether import was successful.
        error: Error code if import failed ('invalid_file' or 'exists').
        receipt: Created Receipt instance if successful.
    """

    success: bool
    error: str | None = None
    receipt: Receipt | None = None


class ReceiptImportService:
    """Service for importing receipts from images or JSON data.

    Handles AI-based image analysis, JSON parsing, and receipt creation
    from external sources.
    """

    def __init__(
        self,
        receipt_repository: ReceiptRepositoryProtocol,
        receipt_creator_service: ReceiptCreatorService,
    ) -> None:
        """Initialize ReceiptImportService.

        Args:
            receipt_repository: Repository for receipt data access.
            receipt_creator_service: Service for creating receipts.
        """
        self.receipt_repository = receipt_repository
        self.receipt_creator_service = receipt_creator_service

    def _clean_json_response(self, text: str) -> str:
        """Extract JSON from markdown code blocks.

        Args:
            text: Text that may contain JSON in code blocks.

        Returns:
            Extracted JSON string or original text if no code blocks found.
        """
        match = re.search(r'```(?:json)?\s*({.*?})\s*```', text, re.DOTALL)
        if match:
            return match.group(1)
        return text.strip()

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

    def _parse_receipt_date(self, date_str: str) -> datetime:
        """Parse receipt date string to datetime.

        Args:
            date_str: Date string in DD.MM.YYYY HH:MM format.

        Returns:
            Timezone-aware datetime instance.
        """
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

    def _check_exist_receipt(
        self,
        user: User,
        number_receipt: int | None,
    ) -> QuerySet[Receipt]:
        """Check if receipt with given number already exists.

        Args:
            user: User to check receipts for.
            number_receipt: Receipt number to check.

        Returns:
            QuerySet of matching receipts.
        """
        return self.receipt_repository.get_by_user_and_number(
            user=user,
            number_receipt=number_receipt,
        )

    def _to_decimal(self, value: Any) -> Decimal:
        """Convert value to Decimal.

        Args:
            value: Value to convert.

        Returns:
            Decimal instance.
        """
        return Decimal(str(value))

    def _to_optional_decimal(self, value: Any) -> Decimal | None:
        """Convert value to Decimal or return None.

        Args:
            value: Value to convert, may be None.

        Returns:
            Decimal instance or None.
        """
        if value is None:
            return None
        return self._to_decimal(value)

    @transaction.atomic
    def process_uploaded_image(
        self,
        *,
        user: User,
        account: Account,
        uploaded_file: UploadedFile,
        analyze_func: (
            Callable[[UploadedFile], str]
            | Callable[[UploadedFile, int | None], str]
            | None
        ) = None,
    ) -> ReceiptImportResult:
        """Process uploaded receipt image and create receipt.

        Analyzes image using AI or custom function, parses JSON response,
        and creates receipt with products.

        Args:
            user: User importing the receipt.
            account: Account to charge for the receipt.
            uploaded_file: Uploaded image file.
            analyze_func: Optional custom analysis function. If None,
                uses default AI analysis.

        Returns:
            ReceiptImportResult with success status and receipt or error.
        """
        try:
            func = analyze_func
            if func is None:
                func = receipts_services.analyze_image_with_ai

            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            if len(params) >= MIN_FUNCTION_PARAMS_COUNT and 'user_id' in params:
                raw = func(uploaded_file, user_id=user.pk)  # type: ignore[call-arg]
            else:
                raw = func(uploaded_file)  # type: ignore[call-arg]
            if raw and 'json' in raw:
                raw = self._clean_json_response(raw)
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            return ReceiptImportResult(success=False, error='invalid_file')

        number_receipt = data.get('number_receipt')
        if self._check_exist_receipt(
            user,
            number_receipt,
        ).exists():
            return ReceiptImportResult(success=False, error='exists')

        receipt = self.receipt_creator_service.create_receipt_with_products(
            user=user,
            account=account,
            receipt_data=ReceiptCreateData(
                receipt_date=self._parse_receipt_date(data['receipt_date']),
                total_sum=self._to_decimal(data['total_sum']),
                number_receipt=data.get('number_receipt'),
                nds10=self._to_optional_decimal(data.get('nds10')),
                nds20=self._to_optional_decimal(data.get('nds20')),
                operation_type=data.get('operation_type', 0),
            ),
            seller_data=SellerCreateData(
                name_seller=str(
                    data.get('name_seller', 'Неизвестный продавец')
                ),
                retail_place_address=data.get('retail_place_address'),
                retail_place=data.get('retail_place'),
            ),
            products_data=data.get('items', []),
        )

        return ReceiptImportResult(success=True, error=None, receipt=receipt)
