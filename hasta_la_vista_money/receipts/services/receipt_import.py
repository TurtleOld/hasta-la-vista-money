import decimal
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts import services as receipts_services
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.users.models import User


@dataclass
class ReceiptImportResult:
    success: bool
    error: str | None = None
    receipt: Receipt | None = None


class ReceiptImportService:
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
        return Receipt.objects.filter(user=user, number_receipt=number_receipt)

    def _create_or_update_seller(
        self,
        data: dict[str, Any],
        user: User,
    ) -> Seller:
        return Seller.objects.update_or_create(
            user=user,
            name_seller=data.get('name_seller'),
            defaults={
                'retail_place_address': data.get(
                    'retail_place_address',
                    'Нет данных',
                ),
                'retail_place': data.get('retail_place', 'Нет данных'),
            },
        )[0]

    def _create_products(
        self,
        data: dict[str, Any],
        user: User,
    ) -> list[Product]:
        products_data = [
            Product(
                user=user,
                product_name=item['product_name'],
                category=item.get('category'),
                price=item['price'],
                quantity=item['quantity'],
                amount=item['amount'],
            )
            for item in data.get('items', [])
        ]
        return Product.objects.bulk_create(products_data)

    def _create_receipt(
        self,
        data: dict[str, Any],
        user: User,
        account: Account,
        seller: Seller,
    ) -> Receipt:
        return Receipt.objects.create(
            user=user,
            account=account,
            number_receipt=data['number_receipt'],
            receipt_date=self._parse_receipt_date(
                data['receipt_date'],
            ),
            nds10=data.get('nds10', 0),
            nds20=data.get('nds20', 0),
            operation_type=data.get('operation_type', 0),
            total_sum=data['total_sum'],
            seller=seller,
        )

    def __init__(
        self,
        account_service: AccountServiceProtocol,
    ) -> None:
        self.account_service = account_service

    def _update_account_balance(
        self,
        account: Account,
        total_sum: decimal.Decimal | str | float,
    ) -> None:
        account_balance = get_object_or_404(Account, pk=account.pk)
        self.account_service.apply_receipt_spend(
            account_balance,
            decimal.Decimal(total_sum),
        )

    @transaction.atomic
    def process_uploaded_image(
        self,
        *,
        user: User,
        account: Account,
        uploaded_file: UploadedFile,
        analyze_func: Callable[[UploadedFile], str] | None = None,
    ) -> ReceiptImportResult:
        try:
            func = analyze_func
            if func is None:
                func = receipts_services.analyze_image_with_ai
            raw = func(uploaded_file)
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

        seller = self._create_or_update_seller(data, user)
        products = self._create_products(data, user)
        receipt = self._create_receipt(
            data,
            user,
            account,
            seller,
        )

        if products:
            receipt.product.set(products)

        self._update_account_balance(
            account,
            decimal.Decimal(data['total_sum']),
        )

        return ReceiptImportResult(success=True, error=None, receipt=receipt)
