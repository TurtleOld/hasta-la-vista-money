import decimal
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.forms.formsets import BaseFormSet

from core.protocols.services import AccountServiceProtocol
from core.repositories.protocols import (
    ProductRepositoryProtocol,
    ReceiptRepositoryProtocol,
    SellerRepositoryProtocol,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import ReceiptForm
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.repositories.account_repository import (  # noqa: E501
        AccountRepository,
    )


class ReceiptCreatorService:
    def __init__(
        self,
        account_service: AccountServiceProtocol,
        account_repository: 'AccountRepository',
        product_repository: ProductRepositoryProtocol,
        receipt_repository: ReceiptRepositoryProtocol,
        seller_repository: SellerRepositoryProtocol,
    ) -> None:
        self.account_service = account_service
        self.account_repository = account_repository
        self.product_repository = product_repository
        self.receipt_repository = receipt_repository
        self.seller_repository = seller_repository

    @transaction.atomic
    def create_manual_receipt(
        self,
        *,
        user: User,
        receipt_form: ReceiptForm,
        product_formset: BaseFormSet[Any],
        seller: Seller,
    ) -> Receipt | None:
        receipt = receipt_form.save(commit=False)
        total_sum = receipt.total_sum
        account = receipt.account
        account_balance = self.account_repository.get_by_id(account.pk)

        if account_balance.user != user:
            return None

        self.account_service.apply_receipt_spend(account_balance, total_sum)

        receipt.user = user
        receipt.seller = seller
        receipt.manual = True
        receipt.save()

        for product_form in product_formset:
            if product_form.cleaned_data and not product_form.cleaned_data.get(
                'DELETE',
                False,
            ):
                product_data = product_form.cleaned_data
                if (
                    product_data.get('product_name')
                    and product_data.get('price')
                    and product_data.get('quantity')
                ):
                    product = self.product_repository.create_product(
                        user=user,
                        product_name=product_data['product_name'],
                        price=product_data['price'],
                        quantity=product_data['quantity'],
                        amount=product_data['amount'],
                    )
                    self.receipt_repository.add_product_to_receipt(
                        receipt,
                        product,
                    )

        return receipt

    def _parse_receipt_date(
        self,
        receipt_date: str | datetime | None,
    ) -> datetime:
        """Parse receipt date from various formats."""
        if receipt_date is None:
            return datetime.now(UTC)
        if isinstance(receipt_date, datetime):
            return receipt_date
        if isinstance(receipt_date, str):
            try:
                return datetime.fromisoformat(receipt_date)
            except (ValueError, AttributeError):
                return datetime.now(UTC)
        return datetime.now(UTC)

    def _create_or_get_seller(
        self,
        data: dict[str, Any],
        user: User,
    ) -> Seller:
        """Create or get seller from JSON data."""
        seller_data = data.get('seller')
        if seller_data and isinstance(seller_data, dict):
            name_seller = seller_data.get('name_seller', '')
            if not name_seller:
                name_seller = 'Неизвестный продавец'
            return self.seller_repository.update_or_create_seller(
                user=user,
                name_seller=name_seller,
                defaults={
                    'retail_place_address': seller_data.get(
                        'retail_place_address',
                        'Нет данных',
                    ),
                    'retail_place': seller_data.get(
                        'retail_place', 'Нет данных'
                    ),
                },
            )
        name_seller = data.get('name_seller', '')
        if not name_seller:
            name_seller = 'Неизвестный продавец'
        return self.seller_repository.update_or_create_seller(
            user=user,
            name_seller=name_seller,
            defaults={
                'retail_place_address': data.get(
                    'retail_place_address',
                    'Нет данных',
                ),
                'retail_place': data.get('retail_place', 'Нет данных'),
            },
        )

    def _create_products_from_json(
        self,
        data: dict[str, Any],
        user: User,
    ) -> list[Product]:
        """Create products from JSON data."""
        products_data = []
        items = data.get('items') or data.get('product', [])

        for item in items:
            if not isinstance(item, dict):
                continue
            product_data = {
                'user': user,
                'product_name': item.get('product_name', ''),
                'category': item.get('category', ''),
                'price': decimal.Decimal(str(item.get('price', 0))),
                'quantity': decimal.Decimal(str(item.get('quantity', 0))),
                'amount': decimal.Decimal(str(item.get('amount', 0))),
            }
            products_data.append(Product(**product_data))

        return self.product_repository.bulk_create_products(products_data)

    @transaction.atomic
    def create_receipt_from_json(
        self,
        *,
        user: User,
        account: Account,
        data: dict[str, Any],
    ) -> Receipt:
        """Create receipt from JSON data.

        Args:
            user: User creating the receipt
            account: Account to charge
            data: Dictionary with receipt data. Can have:
                - seller: dict with seller data OR
                - name_seller: string (for upload image format)
                - product: list of product dicts (API format) OR
                - items: list of product dicts (upload image format)
                - receipt_date: string or datetime
                - total_sum: decimal value
                - number_receipt: int
                - operation_type: int
                - nds10: decimal value (optional)
                - nds20: decimal value (optional)

        Returns:
            Created Receipt instance
        """
        account_balance = self.account_repository.get_by_id(account.pk)

        if account_balance.user != user:
            raise ValueError('Account does not belong to user')

        total_sum_value = data.get('total_sum')
        if total_sum_value is None:
            raise ValueError('total_sum is required')

        total_sum = decimal.Decimal(str(total_sum_value))
        self.account_service.apply_receipt_spend(account_balance, total_sum)

        seller = self._create_or_get_seller(data, user)

        receipt_date = self._parse_receipt_date(data.get('receipt_date'))

        receipt = self.receipt_repository.create_receipt(
            user=user,
            account=account,
            receipt_date=receipt_date,
            seller=seller,
            total_sum=total_sum,
            number_receipt=data.get('number_receipt'),
            operation_type=data.get('operation_type', 0),
            nds10=decimal.Decimal(str(data.get('nds10')))
            if data.get('nds10')
            else None,
            nds20=decimal.Decimal(str(data.get('nds20')))
            if data.get('nds20')
            else None,
            manual=False,
        )

        products = self._create_products_from_json(data, user)
        if products:
            receipt.product.set(products)

        return receipt
