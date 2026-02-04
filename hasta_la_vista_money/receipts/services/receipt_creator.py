from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.forms.formsets import BaseFormSet
from django.utils.translation import gettext_lazy as _

from core.protocols.services import AccountServiceProtocol
from core.repositories.protocols import (
    ProductRepositoryProtocol,
    ReceiptRepositoryProtocol,
    SellerRepositoryProtocol,
)
from hasta_la_vista_money.receipts.forms import ReceiptForm
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.finance_account.repositories.account_repository import (  # noqa: E501
        AccountRepository,
    )


class ReceiptCreatorService:
    """Service for creating receipts with products.

    Handles creation of receipts from various sources (AI, manual entry, import)
    with automatic seller and product management.
    """

    def __init__(
        self,
        account_service: AccountServiceProtocol,
        account_repository: 'AccountRepository',
        product_repository: ProductRepositoryProtocol,
        receipt_repository: ReceiptRepositoryProtocol,
        seller_repository: SellerRepositoryProtocol,
    ) -> None:
        """Initialize ReceiptCreatorService.

        Args:
            account_service: Service for account balance operations.
            account_repository: Repository for account data access.
            product_repository: Repository for product data access.
            receipt_repository: Repository for receipt data access.
            seller_repository: Repository for seller data access.
        """
        self.account_service = account_service
        self.account_repository = account_repository
        self.product_repository = product_repository
        self.receipt_repository = receipt_repository
        self.seller_repository = seller_repository

    @transaction.atomic
    def create_receipt_with_products(
        self,
        *,
        user: User,
        account: 'Account',
        receipt_data: 'ReceiptCreateData',
        seller_data: 'SellerCreateData | None' = None,
        seller_id: int | None = None,
        products_data: Iterable[dict[str, Any]] | None = None,
        manual: bool = False,
    ) -> Receipt:
        """Create receipt and related products from raw data.

        Args:
            user: User creating the receipt.
            account: Account to charge for the receipt.
            receipt_data: Receipt creation data.
            seller_data: Seller creation data (used if seller_id is None).
            seller_id: Existing seller ID (takes precedence over seller_data).
            products_data: Optional iterable of product dictionaries.
            manual: Whether receipt is manually created.

        Returns:
            Created Receipt instance.
        """

        account_balance = self.account_repository.get_by_id(account.pk)
        self.account_service.apply_receipt_spend(
            account_balance,
            receipt_data.total_sum,
        )

        if seller_id is not None:
            try:
                seller = Seller.objects.get(id=seller_id, user=user)
            except Seller.DoesNotExist as err:
                error_msg = (
                    f'Seller with ID {seller_id} not found '
                    'or does not belong to user'
                )
                raise ValueError(error_msg) from err
        elif seller_data is not None:
            seller = self._create_or_update_seller(
                user=user,
                seller_data=seller_data,
            )
        else:
            raise ValueError('Either seller_id or seller_data must be provided')
        receipt = self.receipt_repository.create_receipt(
            user=user,
            account=account,
            seller=seller,
            receipt_date=receipt_data.receipt_date,
            number_receipt=receipt_data.number_receipt,
            nds10=receipt_data.nds10,
            nds20=receipt_data.nds20,
            operation_type=receipt_data.operation_type,
            total_sum=receipt_data.total_sum,
            manual=manual,
        )

        products = self._prepare_products(
            user=user,
            products_data=products_data,
        )
        if products:
            created_products = self.product_repository.bulk_create_products(
                products,
            )
            for product in created_products:
                self.receipt_repository.add_product_to_receipt(receipt, product)

        return receipt

    @transaction.atomic
    def create_manual_receipt(
        self,
        *,
        user: User,
        receipt_form: ReceiptForm,
        product_formset: BaseFormSet[Any],
        seller: Seller,
    ) -> Receipt | None:
        """Create receipt from manual form entry.

        Args:
            user: User creating the receipt.
            receipt_form: Validated receipt form.
            product_formset: Formset with product data.
            seller: Seller instance for the receipt.

        Returns:
            Created Receipt instance, or None if user doesn't own the account.
        """
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

    def _create_or_update_seller(
        self,
        *,
        user: User,
        seller_data: 'SellerCreateData',
    ) -> Seller:
        """Create or update seller from data.

        Args:
            user: User owning the seller.
            seller_data: Seller creation data.

        Returns:
            Seller instance (created or updated).
        """
        name_seller = seller_data.name_seller or str(_('Неизвестный продавец'))
        return self.seller_repository.update_or_create_seller(
            user=user,
            name_seller=name_seller,
            defaults={
                'retail_place_address': seller_data.retail_place_address
                or str(_('Нет данных')),
                'retail_place': seller_data.retail_place
                or str(_('Нет данных')),
            },
        )

    def _prepare_products(
        self,
        *,
        user: User,
        products_data: Iterable[dict[str, Any]] | None,
    ) -> list['Product']:
        """Prepare Product instances from raw data.

        Args:
            user: User owning the products.
            products_data: Iterable of product dictionaries.

        Returns:
            List of Product instances ready for creation.
        """
        products: list[Product] = []
        if products_data is None:
            return products

        for raw_product in products_data:
            product_name = raw_product.get('product_name')
            price = raw_product.get('price')
            quantity = raw_product.get('quantity')
            amount = raw_product.get('amount')

            if product_name is None or price is None or quantity is None:
                continue

            products.append(
                Product(
                    user=user,
                    product_name=str(product_name),
                    category=str(raw_product.get('category', '')),
                    price=Decimal(str(price)),
                    quantity=Decimal(str(quantity)),
                    amount=Decimal(str(amount or 0)),
                    nds_type=raw_product.get('nds_type'),
                    nds_sum=Decimal(str(raw_product.get('nds_sum', 0))),
                ),
            )

        return products


@dataclass
class SellerCreateData:
    """Data for creating or updating a seller.

    Attributes:
        name_seller: Seller name.
        retail_place_address: Optional retail place address.
        retail_place: Optional retail place name.
    """

    name_seller: str
    retail_place_address: str | None = None
    retail_place: str | None = None


@dataclass
class ReceiptCreateData:
    """Data for creating a receipt.

    Attributes:
        receipt_date: Receipt date and time.
        total_sum: Total receipt amount.
        number_receipt: Optional receipt number.
        operation_type: Optional operation type (purchase/return).
        nds10: Optional VAT 10% amount.
        nds20: Optional VAT 20% amount.
    """

    receipt_date: datetime
    total_sum: Decimal
    number_receipt: int | None = None
    operation_type: int | None = None
    nds10: Decimal | None = None
    nds20: Decimal | None = None
