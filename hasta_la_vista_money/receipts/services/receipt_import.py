import inspect
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hasta_la_vista_money.receipts.services.receipt_ai_prompt import (
        analyze_image_with_ai,
    )

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


@dataclass
class ReceiptImportResult:
    success: bool
    error: str | None = None
    receipt: Receipt | None = None


class ReceiptImportService:
    def __init__(
        self,
        receipt_repository: ReceiptRepositoryProtocol,
        receipt_creator_service: ReceiptCreatorService,
    ) -> None:
        self.receipt_repository = receipt_repository
        self.receipt_creator_service = receipt_creator_service

    def _clean_json_response(self, text: str) -> str:
        match = re.search(r'```(?:json)?\s*({.*?})\s*```', text, re.DOTALL)
        if match:
            return match.group(1)
        return text.strip()

    def _normalize_date(self, date_str: str) -> str:
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
        return self.receipt_repository.get_by_user_and_number(
            user=user,
            number_receipt=number_receipt,
        )

    def _to_decimal(self, value: Any) -> Decimal:
        return Decimal(str(value))

    def _to_optional_decimal(self, value: Any) -> Decimal | None:
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
        try:
            func = analyze_func
            if func is None:
                func = receipts_services.analyze_image_with_ai

            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            if len(params) >= 2 and 'user_id' in params:
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
