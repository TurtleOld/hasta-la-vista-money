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
from hasta_la_vista_money.receipts.forms import ProductForm, ReceiptForm
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.receipts.services.receipt_creator import (
    receipt_balance_delta,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.repositories.account_repository import (  # noqa: E501
        AccountRepository,
    )


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
    ) -> None:
        """Initialize ReceiptUpdaterService.

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
                        category=product_data.get('category', ''),
                        price=product_data['price'],
                        quantity=product_data['quantity'],
                        amount=product_data['amount'],
                    )
                    self.receipt_repository.add_product_to_receipt(
                        receipt,
                        product,
                    )
                    new_total_sum += product_data['amount']

        receipt.total_sum = new_total_sum
        receipt.save()

        old_delta = receipt_balance_delta(old_operation_type, old_total_sum)
        new_delta = receipt_balance_delta(
            receipt.operation_type,
            new_total_sum,
        )
        deltas = {old_account_id: -old_delta}
        deltas[receipt.account_id] = (
            deltas.get(receipt.account_id, 0) + new_delta
        )
        self.account_service.apply_account_deltas(deltas)
        return receipt
