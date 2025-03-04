from django.test import TestCase
from django.urls import reverse_lazy
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import ReceiptForm
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.users.models import User


class TestReceipt(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_receipt.yaml',
        'receipt_seller.yaml',
        'receipt_product.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.receipt = Receipt.objects.get(pk=1)
        self.seller = Seller.objects.get(pk=1)
        self.product = Product.objects.get(pk=1)

    def test_receipt_list(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('receipts:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_receipt_create(self):
        self.client.force_login(self.user)
        url = reverse_lazy('receipts:create')

        new_product_data = {
            'user': self.user,
            'product_name': 'Яблоко',
            'price': 10,
            'quantity': 1,
            'amount': 10,
            'nds_type': 1,
            'nds_sum': 1.3,
        }

        new_product = Product.objects.create(**new_product_data)

        new_seller_data = {
            'user': self.user,
            'name_seller': 'ООО Рога и Копыта',
        }

        new_seller = Seller.objects.create(**new_seller_data)

        new_receipt_data = {
            'user': self.user,
            'account': self.account,
            'receipt_date': '2023-06-28 21:24',
            'number_receipt': 111,
            'operation_type': 1,
            'total_sum': 10,
            'seller': new_seller,
        }
        new_receipt = Receipt.objects.create(**new_receipt_data)
        new_receipt.product.add(new_product)

        form_receipt = ReceiptForm(data=new_receipt_data)
        self.assertTrue(form_receipt.is_valid())

        response_receipt = self.client.post(url, data=form_receipt.data)
        self.assertEqual(
            response_receipt.status_code,
            constants.SUCCESS_CODE,
        )

    def test_receipt_delete(self):
        self.client.force_login(self.user)
