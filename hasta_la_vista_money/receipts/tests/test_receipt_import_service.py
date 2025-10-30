from __future__ import annotations

import io
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts import services as receipts_services
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.receipts.services.receipt_import import (
    ReceiptImportService,
)
from hasta_la_vista_money.users.models import User


class ReceiptImportServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='tester', password='pass', email='t@example.com'
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )

    def test_process_uploaded_image_success(self):
        # Prepare fake image file
        uploaded_file = SimpleUploadedFile(
            'test.jpg',
            io.BytesIO(b'fake-bytes').getvalue(),
            content_type='image/jpeg',
        )

        # Fake JSON receipt response
        data = {
            'name_seller': 'Shop',
            'retail_place_address': 'Address',
            'retail_place': 'Place',
            'total_sum': 150.5,
            'operation_type': 2,
            'receipt_date': timezone.now().strftime('%d.%m.%Y %H:%M'),
            'number_receipt': 123456,
            'nds10': 0,
            'nds20': 0,
            'items': [
                {
                    'product_name': 'Item A',
                    'category': 'Misc',
                    'price': 50.5,
                    'quantity': 1,
                    'amount': 50.5,
                },
                {
                    'product_name': 'Item B',
                    'category': 'Misc',
                    'price': 100.0,
                    'quantity': 1,
                    'amount': 100.0,
                },
            ],
        }

        # Patch analyze_image_with_ai to return JSON
        # import moved to module level

        def fake_analyze(_):
            return json.dumps(data)

        old_fn = receipts_services.analyze_image_with_ai
        receipts_services.analyze_image_with_ai = fake_analyze
        try:
            result = ReceiptImportService.process_uploaded_image(
                user=self.user,
                account=self.account,
                uploaded_file=uploaded_file,
            )
        finally:
            receipts_services.analyze_image_with_ai = old_fn

        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.receipt)
        self.assertTrue(
            Receipt.objects.filter(
                user=self.user, number_receipt=data['number_receipt']
            ).exists()
        )

        self.account.refresh_from_db()
        self.assertEqual(float(self.account.balance), 1000 - data['total_sum'])
