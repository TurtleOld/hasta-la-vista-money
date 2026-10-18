"""Receipt deletion removes its products in a constant number of queries."""

from decimal import Decimal
from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()


class ReceiptDeleterProductQueriesTests(TestCase):
    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'finance_account.yaml',
        'receipt_seller.yaml',
    ]

    def setUp(self) -> None:
        self.user = UserType.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.seller = Seller.objects.get(pk=1)
        self.service = ApplicationContainer().receipts.receipt_deleter_service()

    def _receipt_with_products(self, count: int) -> Receipt:
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=self.seller,
            receipt_date=timezone.now(),
            operation_type=constants.RECEIPT_OPERATION_PURCHASE,
            total_sum=Decimal(count),
        )
        products = [
            Product.objects.create(
                user=self.user,
                product_name=f'item {index}',
                price=Decimal(1),
                quantity=Decimal(1),
                amount=Decimal(1),
            )
            for index in range(count)
        ]
        receipt.product.add(*products)
        return receipt

    def _delete_queries(self, receipt: Receipt) -> int:
        with CaptureQueriesContext(connection) as queries:
            self.service.delete_receipt(user=self.user, receipt=receipt)
        return len(queries)

    def test_query_count_does_not_grow_with_products(self) -> None:
        small = self._receipt_with_products(1)
        large = self._receipt_with_products(5)
        large_product_ids = list(large.product.values_list('pk', flat=True))

        self.assertEqual(
            self._delete_queries(small),
            self._delete_queries(large),
        )
        self.assertFalse(Receipt.objects.filter(pk=large.pk).exists())
        self.assertFalse(
            Product.objects.filter(pk__in=large_product_ids).exists(),
        )
