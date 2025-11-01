import decimal
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services import AccountService
from hasta_la_vista_money.receipts import services as receipts_services
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller


@dataclass
class ReceiptImportResult:
    success: bool
    error: str | None = None
    receipt: Receipt | None = None


class ReceiptImportService:
    @staticmethod
    def _clean_json_response(text: str) -> str:
        match = re.search(r'```(?:json)?\s*({.*?})\s*```', text, re.DOTALL)
        if match:
            return match.group(1)
        return text.strip()

    @staticmethod
    def _normalize_date(date_str: str) -> str:
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

    @staticmethod
    def _parse_receipt_date(date_str: str) -> datetime:
        normalized_date = ReceiptImportService._normalize_date(date_str)
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

    @staticmethod
    def _check_exist_receipt(user, number_receipt: int | None):
        return Receipt.objects.filter(user=user, number_receipt=number_receipt)

    @staticmethod
    def _create_or_update_seller(data: dict[str, Any], user) -> Seller:
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

    @staticmethod
    def _create_products(data: dict[str, Any], user) -> list[Product]:
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

    @staticmethod
    def _create_receipt(
        data: dict[str, Any],
        user,
        account: Account,
        seller: Seller,
    ) -> Receipt:
        return Receipt.objects.create(
            user=user,
            account=account,
            number_receipt=data['number_receipt'],
            receipt_date=ReceiptImportService._parse_receipt_date(
                data['receipt_date'],
            ),
            nds10=data.get('nds10', 0),
            nds20=data.get('nds20', 0),
            operation_type=data.get('operation_type', 0),
            total_sum=data['total_sum'],
            seller=seller,
        )

    @staticmethod
    def _update_account_balance(account: Account, total_sum) -> None:
        account_balance = get_object_or_404(Account, pk=account.pk)
        AccountService.apply_receipt_spend(
            account_balance,
            decimal.Decimal(total_sum),
        )

    @staticmethod
    @transaction.atomic
    def process_uploaded_image(
        *,
        user,
        account: Account,
        uploaded_file,
        analyze_func=None,
    ) -> ReceiptImportResult:
        try:
            func = analyze_func
            if func is None:
                func = receipts_services.analyze_image_with_ai
            raw = func(uploaded_file)
            if raw and 'json' in raw:
                raw = ReceiptImportService._clean_json_response(raw)
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            return ReceiptImportResult(success=False, error='invalid_file')

        number_receipt = data.get('number_receipt')
        if ReceiptImportService._check_exist_receipt(
            user,
            number_receipt,
        ).exists():
            return ReceiptImportResult(success=False, error='exists')

        seller = ReceiptImportService._create_or_update_seller(data, user)
        products = ReceiptImportService._create_products(data, user)
        receipt = ReceiptImportService._create_receipt(
            data,
            user,
            account,
            seller,
        )

        if products:
            receipt.product.set(products)

        ReceiptImportService._update_account_balance(account, data['total_sum'])

        return ReceiptImportResult(success=True, error=None, receipt=receipt)
