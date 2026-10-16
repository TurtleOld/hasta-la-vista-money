from typing import ClassVar

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


class ReceiptDeleteApiOwnershipTest(TestCase):
    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'finance_account.yaml',
        'receipt_receipt.yaml',
        'receipt_seller.yaml',
        'receipt_product.yaml',
    ]

    def test_foreign_and_missing_receipt_give_same_response(self) -> None:
        receipt = Receipt.objects.select_related('user').first()
        if receipt is None:
            self.fail('No receipt in fixtures')
        stranger = User.objects.create_user(username='stranger', password='x')
        client = APIClient()
        client.force_authenticate(stranger)

        foreign = client.delete(
            reverse('receipts:delete_api', kwargs={'pk': receipt.pk}),
        )
        missing = client.delete(
            reverse('receipts:delete_api', kwargs={'pk': receipt.pk + 1000}),
        )

        self.assertEqual(foreign.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(foreign.json(), missing.json())
        self.assertTrue(Receipt.objects.filter(pk=receipt.pk).exists())
