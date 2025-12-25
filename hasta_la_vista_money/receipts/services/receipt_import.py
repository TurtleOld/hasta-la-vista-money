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

    def _convert_to_decimal(self, value: str | int | float | Decimal) -> Decimal:
        """Convert value to Decimal.

        Args:
            value: Value to convert (str, int, float, or Decimal).

        Returns:
            Decimal instance.
        """
        return Decimal(str(value))

    def _convert_to_optional_decimal(
        self,
        value: str | int | float | Decimal | None,
    ) -> Decimal | None:
        """Convert value to Decimal or return None.

        Args:
            value: Value to convert, may be None.

        Returns:
            Decimal instance or None.
        """
        if value is None:
            return None
        return self._convert_to_decimal(value)

    def _get_analysis_function(
        self,
        analyze_func: (
            Callable[[UploadedFile], str]
            | Callable[[UploadedFile, int | None], str]
            | None
        ),
    ) -> Callable[[UploadedFile], str] | Callable[[UploadedFile, int | None], str]:
        """Get analysis function to use for image processing.

        Args:
            analyze_func: Optional custom analysis function.

        Returns:
            Analysis function to use (custom or default AI function).
        """
        if analyze_func is None:
            return receipts_services.analyze_image_with_ai
        return analyze_func

    def _analyze_image(
        self,
        uploaded_file: UploadedFile,
        analyze_func: (
            Callable[[UploadedFile], str]
            | Callable[[UploadedFile, int | None], str]
        ),
        user_id: int | None = None,
    ) -> str:
        """Analyze receipt image and extract JSON data.

        Args:
            uploaded_file: Uploaded image file.
            analyze_func: Function to analyze the image.
            user_id: Optional user ID for rate limiting.

        Returns:
            JSON string with receipt data.

        Raises:
            json.JSONDecodeError: If JSON parsing fails.
            ValueError: If data processing fails.
            TypeError: If data type conversion fails.
        """
        sig = inspect.signature(analyze_func)
        params = list(sig.parameters.keys())
        if len(params) >= MIN_FUNCTION_PARAMS_COUNT and 'user_id' in params:
            raw = analyze_func(uploaded_file, user_id=user_id)  # type: ignore[call-arg]
        else:
            raw = analyze_func(uploaded_file)  # type: ignore[call-arg]

        if raw and 'json' in raw:
            raw = self._clean_json_response(raw)

        return raw

    def _parse_receipt_json(self, json_string: str) -> dict[str, Any]:
        """Parse JSON string to receipt data dictionary.

        Args:
            json_string: JSON string with receipt data.

        Returns:
            Dictionary with receipt data.

        Raises:
            json.JSONDecodeError: If JSON parsing fails.
        """
        return json.loads(json_string)

    def _validate_receipt_data(
        self,
        user: User,
        receipt_data: dict[str, Any],
    ) -> ReceiptImportResult | None:
        """Validate receipt data and check for duplicates.

        Args:
            user: User importing the receipt.
            receipt_data: Parsed receipt data dictionary.

        Returns:
            ReceiptImportResult with error if validation fails, None otherwise.
        """
        number_receipt = receipt_data.get('number_receipt')
        if number_receipt and self._check_exist_receipt(
            user,
            number_receipt,
        ).exists():
            return ReceiptImportResult(success=False, error='exists')
        return None

    def _create_receipt_from_data(
        self,
        user: User,
        account: Account,
        receipt_data: dict[str, Any],
    ) -> Receipt:
        """Create receipt from parsed data dictionary.

        Args:
            user: User creating the receipt.
            account: Account to charge for the receipt.
            receipt_data: Parsed receipt data dictionary.

        Returns:
            Created Receipt instance.
        """
        return self.receipt_creator_service.create_receipt_with_products(
            user=user,
            account=account,
            receipt_data=ReceiptCreateData(
                receipt_date=self._parse_receipt_date(
                    receipt_data['receipt_date'],
                ),
                total_sum=self._convert_to_decimal(receipt_data['total_sum']),
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
        validates data, and creates receipt with products.

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
            func = self._get_analysis_function(analyze_func)
            raw_json = self._analyze_image(uploaded_file, func, user.pk)
            receipt_data = self._parse_receipt_json(raw_json)
        except (json.JSONDecodeError, ValueError, TypeError):
            return ReceiptImportResult(success=False, error='invalid_file')

        validation_result = self._validate_receipt_data(user, receipt_data)
        if validation_result is not None:
            return validation_result

        receipt = self._create_receipt_from_data(user, account, receipt_data)

        return ReceiptImportResult(success=True, error=None, receipt=receipt)
