from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.shortcuts import get_object_or_404

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services import AccountService
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller

if TYPE_CHECKING:
    from hasta_la_vista_money.receipts.forms import ProductFormSet, ReceiptForm


class ReceiptCreatorService:
    @staticmethod
    @transaction.atomic
    def create_manual_receipt(
        *,
        user,
        receipt_form: ReceiptForm,
        product_formset: ProductFormSet,
        seller: Seller,
    ) -> Receipt | None:
        receipt = receipt_form.save(commit=False)
        total_sum = receipt.total_sum
        account = receipt.account
        account_balance = get_object_or_404(Account, id=account.id)

        if account_balance.user != user:
            return None

        AccountService.apply_receipt_spend(account_balance, total_sum)

        receipt.user = user
        receipt.seller = seller
        receipt.manual = True
        receipt.save()

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

        return receipt
