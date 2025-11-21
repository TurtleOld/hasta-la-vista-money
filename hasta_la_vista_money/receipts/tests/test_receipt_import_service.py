import io
import json
from typing import Any, TypedDict

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts import services as receipts_services
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


class ReceiptImportServiceTestsData(TypedDict):
    name_seller: str
    retail_place_address: str
    retail_place: str
    total_sum: float
    operation_type: int
    receipt_date: str
    number_receipt: int
    nds10: float
    nds20: float
    items: list[dict[str, Any]]


class ReceiptImportServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='tester',
            password='pass',
            email='t@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.container = ApplicationContainer()
        self.receipt_import_service = (
            self.container.receipts.receipt_import_service()
        )

    def test_process_uploaded_image_success(self) -> None:
        # Prepare fake image file
        uploaded_file = SimpleUploadedFile(
            'test.jpg',
            io.BytesIO(b'fake-bytes').getvalue(),
            content_type='image/jpeg',
        )

        # Fake JSON receipt response
        data: ReceiptImportServiceTestsData = {
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

        def fake_analyze(_):
            return json.dumps(data)

        old_fn = receipts_services.analyze_image_with_ai
        receipts_services.analyze_image_with_ai = fake_analyze
        try:
            result = self.receipt_import_service.process_uploaded_image(
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
                user=self.user,
                number_receipt=data['number_receipt'],
            ).exists(),
        )

        self.account.refresh_from_db()
        total_sum: float = float(data['total_sum'])
        self.assertEqual(float(self.account.balance), 1000 - total_sum)
