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
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.repositories.account_repository import (  # noqa: E501
        AccountRepository,
    )


class ReceiptUpdaterService:
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
    def update_receipt(
        self,
        *,
        user: User,
        receipt: Receipt,
        form: ReceiptForm,
        product_formset: BaseFormSet[ProductForm],
    ) -> Receipt:
        old_total_sum = receipt.total_sum
        old_account = receipt.account
        receipt = form.save()
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

        new_account = receipt.account

        old_account_obj = self.account_repository.get_by_id(old_account.pk)
        new_account_obj = self.account_repository.get_by_id(new_account.pk)
        self.account_service.reconcile_account_balances(
            old_account=old_account_obj,
            new_account=new_account_obj,
            old_total_sum=old_total_sum,
            new_total_sum=new_total_sum,
        )

        return receipt
