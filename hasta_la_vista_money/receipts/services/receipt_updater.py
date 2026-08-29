from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction
from django.forms.formsets import BaseFormSet

from core.protocols.services import AccountServiceProtocol
from core.repositories.protocols import (
    ProductRepositoryProtocol,
    ReceiptRepositoryProtocol,
    SellerRepositoryProtocol,
)
from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.forms import ProductForm, ReceiptForm
from hasta_la_vista_money.receipts.models import (
    ProductCategory,
    ProductCategorySource,
    Receipt,
)
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_name,
)
from hasta_la_vista_money.receipts.protocols.services import (
    ProductCategoryCorrectionServiceProtocol,
)
from hasta_la_vista_money.receipts.services.receipt_creator import (
    receipt_balance_delta,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.repositories.account_repository import (  # noqa: E501
        AccountRepository,
    )


@dataclass(frozen=True)
class _PreviousProductsSnapshot:
    """Categories and ids of a receipt's rows before an update."""

    categories: dict[str, int | None]
    ids: set[int]


class ReceiptUpdaterService:
    """Service for updating receipts with products.

    Handles updating receipts and their products with automatic account
    balance reconciliation.
    """

    def __init__(
        self,
        account_service: AccountServiceProtocol,
        account_repository: 'AccountRepository',
        product_repository: ProductRepositoryProtocol,
        receipt_repository: ReceiptRepositoryProtocol,
        seller_repository: SellerRepositoryProtocol,
        category_correction_service: ProductCategoryCorrectionServiceProtocol,
    ) -> None:
        """Initialize ReceiptUpdaterService.

        Args:
            account_service: Service for account balance operations.
            account_repository: Repository for account data access.
            product_repository: Repository for product data access.
            receipt_repository: Repository for receipt data access.
            seller_repository: Repository for seller data access.
            category_correction_service: Service that remembers human
                category corrections.
        """
        self.account_service = account_service
        self.account_repository = account_repository
        self.product_repository = product_repository
        self.receipt_repository = receipt_repository
        self.seller_repository = seller_repository
        self.category_correction_service = category_correction_service

    @transaction.atomic
    def update_receipt(
        self,
        *,
        user: User,
        receipt: Receipt,
        form: ReceiptForm,
        product_formset: BaseFormSet[ProductForm],
    ) -> Receipt:
        """Update receipt and its products.

        Automatically reconciles account balances if account or total changes.

        Args:
            user: User updating the receipt.
            receipt: Receipt instance to update.
            form: Validated receipt form.
            product_formset: Formset with product data.

        Returns:
            Updated Receipt instance.
        """
        receipt = Receipt.objects.select_for_update().get(pk=receipt.pk)
        old_total_sum = receipt.total_sum
        old_account_id = receipt.account_id
        old_operation_type = receipt.operation_type
        previous_products = list(receipt.product.all())
        previous = _PreviousProductsSnapshot(
            categories={
                normalize_product_name(product.product_name): (
                    product.category_id
                )
                for product in previous_products
            },
            ids={product.pk for product in previous_products},
        )
        form.instance = receipt
        for field_name in (
            'seller',
            'account',
            'receipt_date',
            'number_receipt',
            'operation_type',
            'nds10',
            'nds20',
        ):
            setattr(receipt, field_name, form.cleaned_data[field_name])
        if receipt.operation_type is None:
            raise ValueError('Receipt operation type is required')
        receipt.operation_type = int(receipt.operation_type)
        receipt.save()
        receipt.product.clear()
        new_total_sum = Decimal('0.00')

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
                        category=product_data['category'],
                        category_source=ProductCategorySource.MANUAL,
                        price=product_data['price'],
                        quantity=product_data['quantity'],
                        amount=product_data['amount'],
                    )
                    self.receipt_repository.add_product_to_receipt(
                        receipt,
                        product,
                    )
                    new_total_sum += product_data['amount']

                    self._remember_category_correction(
                        user=user,
                        product_name=product_data['product_name'],
                        category=product_data['category'],
                        previous=previous,
                    )

        if receipt.manual:
            receipt.total_sum = new_total_sum
        receipt.adjustment = receipt.total_sum - new_total_sum
        receipt.requires_attention = receipt.adjustment != 0
        receipt.attention_reason = (
            str(constants.RECEIPT_ATTENTION_REASON_TOTAL_MISMATCH)
            if receipt.requires_attention
            else ''
        )
        receipt.save()

        old_delta = receipt_balance_delta(old_operation_type, old_total_sum)
        new_delta = receipt_balance_delta(
            receipt.operation_type,
            receipt.total_sum,
        )
        deltas = {old_account_id: -old_delta}
        deltas[receipt.account_id] = (
            deltas.get(receipt.account_id, 0) + new_delta
        )
        self.account_service.apply_account_deltas(deltas)
        return receipt

    def _remember_category_correction(
        self,
        *,
        user: User,
        product_name: str,
        category: ProductCategory | None,
        previous: _PreviousProductsSnapshot,
    ) -> None:
        """Pin a category that the human actually changed or newly set.

        Only a real correction is remembered: if the submitted category
        matches the one the product already had (by normalized name), nothing
        is pinned, so the automatic stages keep working for names the human
        never corrected.
        """
        if category is None:
            return
        normalized_name = normalize_product_name(product_name)
        if previous.categories.get(normalized_name) == category.pk:
            return
        self.category_correction_service.apply_correction(
            user=user,
            product_name=product_name,
            category=category,
            exclude_product_ids=previous.ids,
        )
