from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services import AccountService
from hasta_la_vista_money.receipts.models import Product, Receipt

if TYPE_CHECKING:
    from hasta_la_vista_money.receipts.forms import ProductFormSet, ReceiptForm


class ReceiptUpdaterService:
    @staticmethod
    @transaction.atomic
    def update_receipt(
        *,
        user,
        receipt: Receipt,
        form: ReceiptForm,
        product_formset: ProductFormSet,
    ) -> Receipt:
        old_total_sum = receipt.total_sum
        old_account = receipt.account

        receipt = form.save()

        # Пересобираем товары
        receipt.product.clear()

        new_total_sum = Decimal('0.00')
        for product_form in product_formset:
            if product_form.cleaned_data and not product_form.cleaned_data.get(
                'DELETE', False
            ):
                product_data = product_form.cleaned_data
                if (
                    product_data.get('product_name')
                    and product_data.get('price')
                    and product_data.get('quantity')
                ):
                    product = Product.objects.create(
                        user=user,
                        product_name=product_data['product_name'],
                        price=product_data['price'],
                        quantity=product_data['quantity'],
                        amount=product_data['amount'],
                    )
                    receipt.product.add(product)
                    new_total_sum += product_data['amount']

        receipt.total_sum = new_total_sum
        receipt.save()

        new_account = receipt.account

        # Корректировка балансов через сервис аккаунтов
        old_account_obj = Account.objects.get(id=old_account.id)
        new_account_obj = Account.objects.get(id=new_account.id)
        AccountService.adjust_on_receipt_update(
            old_account=old_account_obj,
            new_account=new_account_obj,
            old_total_sum=old_total_sum,
            new_total_sum=new_total_sum,
        )

        return receipt
