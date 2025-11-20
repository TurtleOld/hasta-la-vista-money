from decimal import Decimal

from django.db import transaction
from django.forms.formsets import BaseFormSet

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import ProductForm, ReceiptForm
from hasta_la_vista_money.receipts.models import Product, Receipt
from hasta_la_vista_money.users.models import User


class ReceiptUpdaterService:
    def __init__(
        self,
        account_service: AccountServiceProtocol,
    ) -> None:
        self.account_service = account_service

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

        old_account_obj = Account.objects.get(pk=old_account.pk)
        new_account_obj = Account.objects.get(pk=new_account.pk)
        self.account_service.reconcile_account_balances(
            old_account=old_account_obj,
            new_account=new_account_obj,
            old_total_sum=old_total_sum,
            new_total_sum=new_total_sum,
        )

        return receipt
