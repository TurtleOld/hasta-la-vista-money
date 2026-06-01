"""Tests for the background receipt processing flow.

Covers PendingReceiptService new methods, the Celery task, and the upload /
retry / counter views. Inference is always mocked — no network calls.
"""

import io
from decimal import Decimal
from typing import Any
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    PendingReceiptStatus,
    Product,
    Receipt,
    ReceiptImageHash,
    Seller,
)
from hasta_la_vista_money.receipts.services.pending_receipt_service import (
    PendingReceiptService,
    compute_image_hash,
)
from hasta_la_vista_money.receipts.tasks import (
    cleanup_stale_pending_receipts,
    process_pending_receipt,
)
from hasta_la_vista_money.receipts.validators.parsed_receipt import (
    ReceiptParseValidationError,
    validate_receipt_parse_payload,
)
from hasta_la_vista_money.users.models import User


def _image_bytes(image_format: str, color: str = 'white') -> bytes:
    image_bytes = io.BytesIO()
    Image.new('RGB', (1, 1), color).save(image_bytes, format=image_format)
    return image_bytes.getvalue()


JPEG_BYTES = _image_bytes('JPEG')
JPEG_BYTES_ALT = _image_bytes('JPEG', 'red')
JPEG_BYTES_DUPLICATE = _image_bytes('JPEG', 'blue')
PNG_BYTES = _image_bytes('PNG', 'green')


def _fake_payload() -> dict[str, Any]:
    return {
        'name_seller': 'Shop',
        'retail_place_address': 'Address',
        'retail_place': 'Place',
        'total_sum': 100.0,
        'operation_type': 1,
        'receipt_date': timezone.now().strftime('%d.%m.%Y %H:%M'),
        'number_receipt': 42,
        'nds10': 0,
        'nds20': 0,
        'items': [
            {
                'product_name': 'Item',
                'category': 'Misc',
                'price': 100.0,
                'quantity': 1,
                'amount': 100.0,
            },
        ],
    }


class PendingReceiptServiceHashTests(TestCase):
    """Hash computation and duplicate detection."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='hash-user',
            password='pass',  # nosec B106: test-only password
            email='h@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.service: PendingReceiptService = (
            ApplicationContainer().receipts.pending_receipt_service()
        )

    def test_compute_image_hash_is_deterministic(self) -> None:
        upload = SimpleUploadedFile(
            'a.jpg',
            io.BytesIO(b'same-bytes').getvalue(),
            content_type='image/jpeg',
        )
        first = compute_image_hash(upload)
        second = compute_image_hash(upload)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_find_duplicate_pending_returns_existing_processing(self) -> None:
        upload = SimpleUploadedFile(
            'a.jpg',
            b'pending-bytes',
            content_type='image/jpeg',
        )
        image_hash = compute_image_hash(upload)
        self.service.create_processing_job(
            user=self.user,
            account=self.account,
            image_file=upload,
            image_hash=image_hash,
        )

        match = self.service.find_duplicate(
            user=self.user,
            image_hash=image_hash,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.kind, 'pending')

    def test_failed_pending_does_not_block_reupload(self) -> None:
        upload = SimpleUploadedFile(
            'a.jpg',
            b'bytes',
            content_type='image/jpeg',
        )
        image_hash = compute_image_hash(upload)
        pending = self.service.create_processing_job(
            user=self.user,
            account=self.account,
            image_file=upload,
            image_hash=image_hash,
        )
        self.service.mark_failed(
            pending_receipt=pending,
            error_message='boom',
        )

        match = self.service.find_duplicate(
            user=self.user,
            image_hash=image_hash,
        )
        self.assertIsNone(match)


class ProcessPendingReceiptTaskTests(TestCase):
    """The Celery task transitions state and never raises out."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='task-user',
            password='pass',  # nosec B106: test-only password
            email='task@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.service: PendingReceiptService = (
            ApplicationContainer().receipts.pending_receipt_service()
        )

    def _create_pending(self) -> PendingReceipt:
        upload = SimpleUploadedFile(
            'r.jpg',
            b'image-bytes',
            content_type='image/jpeg',
        )
        return self.service.create_processing_job(
            user=self.user,
            account=self.account,
            image_file=upload,
            image_hash=compute_image_hash(upload),
        )

    def test_task_marks_ready_on_success(self) -> None:
        pending = self._create_pending()
        with mock.patch(
            'hasta_la_vista_money.receipts.tasks._run_fns_pipeline',
            return_value=_fake_payload(),
        ):
            process_pending_receipt(pending.pk)

        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingReceiptStatus.READY)
        self.assertEqual(pending.error_message, '')
        self.assertEqual(pending.receipt_data['name_seller'], 'Shop')

    def test_task_marks_ready_with_warning_on_total_mismatch(self) -> None:
        pending = self._create_pending()
        payload = _fake_payload()
        payload['total_sum'] = 120.0
        with mock.patch(
            'hasta_la_vista_money.receipts.tasks._run_fns_pipeline',
            return_value=payload,
        ):
            process_pending_receipt(pending.pk)

        pending.refresh_from_db()
        self.assertEqual(
            pending.status,
            PendingReceiptStatus.READY_WITH_WARNING,
        )
        self.assertEqual(pending.error_message, '')

    def test_task_marks_failed_on_pipeline_error(self) -> None:
        pending = self._create_pending()
        with mock.patch(
            'hasta_la_vista_money.receipts.tasks._run_fns_pipeline',
            side_effect=ValueError('pipeline error'),
        ):
            process_pending_receipt(pending.pk)

        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingReceiptStatus.FAILED)
        self.assertNotEqual(pending.error_message, '')

    def test_cleanup_purges_expired_rows(self) -> None:
        pending = self._create_pending()
        PendingReceipt.objects.filter(pk=pending.pk).update(
            expires_at=timezone.now() - timezone.timedelta(hours=1),
        )
        result = cleanup_stale_pending_receipts()
        self.assertEqual(result['purged'], 1)
        self.assertFalse(
            PendingReceipt.objects.filter(pk=pending.pk).exists(),
        )


class PendingReceiptConversionTests(TestCase):
    """Conversion from pending receipt keeps all parsed products."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='conversion-user',
            password='pass',  # nosec B106: test-only password
            email='conversion@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.service: PendingReceiptService = (
            ApplicationContainer().receipts.pending_receipt_service()
        )

    def test_convert_to_receipt_keeps_multiple_items(self) -> None:
        payload = _fake_payload()
        payload['total_sum'] = 232.0
        payload['items'] = [
            {
                'product_name': 'Услуги сервиса Доставка',
                'category': 'Доставка',
                'price': 169.0,
                'quantity': 1,
                'amount': 169.0,
            },
            {
                'product_name': 'Услуги сервиса Авито Доставка для продавца',
                'category': 'Доставка',
                'price': 63.0,
                'quantity': 1,
                'amount': 63.0,
            },
        ]
        pending = PendingReceipt.objects.create(
            user=self.user,
            account=self.account,
            status=PendingReceiptStatus.READY,
            receipt_data=payload,
        )

        receipt = self.service.convert_to_receipt(pending_receipt=pending)

        products = list(
            Product.objects.filter(receipt_products=receipt).order_by('pk'),
        )
        self.assertEqual(
            timezone.localtime(receipt.receipt_date).strftime('%d.%m.%Y %H:%M'),
            payload['receipt_date'],
        )
        self.assertEqual(len(products), 2)
        self.assertEqual(
            [product.product_name for product in products],
            [
                'Услуги сервиса Доставка',
                'Услуги сервиса Авито Доставка для продавца',
            ],
        )


class ReceiptParseValidatorTests(TestCase):
    """Receipt-inference payload validation."""

    def test_valid_payload_is_normalized(self) -> None:
        result = validate_receipt_parse_payload(_fake_payload())

        normalized = result.to_dict()

        self.assertEqual(normalized['total_sum'], '100.00')
        self.assertEqual(normalized['operation_type'], 1)
        self.assertEqual(normalized['items'][0]['amount'], '100.00')

    def test_short_year_receipt_date_is_normalized(self) -> None:
        payload = _fake_payload()
        payload['receipt_date'] = '20.05.23 14:30'

        result = validate_receipt_parse_payload(payload)

        self.assertEqual(result.receipt_date, '20.05.2023 14:30')

    def test_rejects_invalid_receipt_date(self) -> None:
        payload = _fake_payload()
        payload['receipt_date'] = '2023/05/20 14:30'

        with self.assertRaises(ReceiptParseValidationError):
            validate_receipt_parse_payload(payload)

    def test_rejects_missing_required_field(self) -> None:
        payload = _fake_payload()
        del payload['receipt_date']

        with self.assertRaises(ReceiptParseValidationError):
            validate_receipt_parse_payload(payload)

    def test_rejects_unknown_fields(self) -> None:
        payload = _fake_payload()
        payload['debug_prompt'] = 'leak'

        with self.assertRaises(ReceiptParseValidationError):
            validate_receipt_parse_payload(payload)

    def test_allows_total_sum_mismatch_for_review_warning(self) -> None:
        payload = _fake_payload()
        payload['total_sum'] = '150.00'

        result = validate_receipt_parse_payload(payload)

        self.assertEqual(result.total_sum, Decimal('150.00'))


class UploadImageViewTests(TestCase):
    """The view enqueues a task and redirects to the list — no inference."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='upload-user',
            password='pass',  # nosec B106: test-only password
            email='upload@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_upload_creates_processing_pending_and_dispatches(self) -> None:
        upload = SimpleUploadedFile(
            'r.jpg',
            JPEG_BYTES,
            content_type='image/jpeg',
        )
        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_pending_receipt',
        ) as task_mock:
            task_mock.delay.return_value = mock.Mock(id='task-id-1')
            response = self.client.post(
                reverse('receipts:upload'),
                {'file': upload, 'account': self.account.pk},
            )

        self.assertRedirects(response, reverse('receipts:list'))
        pending = PendingReceipt.objects.get(user=self.user)
        self.assertEqual(pending.status, PendingReceiptStatus.PROCESSING)
        self.assertEqual(pending.task_id, 'task-id-1')
        task_mock.delay.assert_called_once_with(pending.pk)

    def test_upload_creates_multiple_processing_jobs(self) -> None:
        uploads = [
            SimpleUploadedFile(
                'r1.jpg',
                JPEG_BYTES_ALT,
                content_type='image/jpeg',
            ),
            SimpleUploadedFile(
                'r2.png',
                PNG_BYTES,
                content_type='image/png',
            ),
        ]
        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_pending_receipt',
        ) as task_mock:
            task_mock.delay.side_effect = [
                mock.Mock(id='task-id-1'),
                mock.Mock(id='task-id-2'),
            ]
            response = self.client.post(
                reverse('receipts:upload'),
                {'file': uploads, 'account': self.account.pk},
            )

        self.assertRedirects(response, reverse('receipts:list'))
        pending_receipts = PendingReceipt.objects.filter(user=self.user)
        self.assertEqual(pending_receipts.count(), 2)
        self.assertEqual(task_mock.delay.call_count, 2)

    def test_upload_rejects_duplicate_against_saved_receipt(self) -> None:
        upload = SimpleUploadedFile(
            'r.jpg',
            JPEG_BYTES_DUPLICATE,
            content_type='image/jpeg',
        )
        image_hash = compute_image_hash(upload)
        seller = Seller.objects.create(
            user=self.user,
            name_seller='S',
        )
        receipt = Receipt.objects.create(
            receipt_date=timezone.now(),
            user=self.user,
            account=self.account,
            seller=seller,
            total_sum=10,
        )
        ReceiptImageHash.objects.create(
            user=self.user,
            receipt=receipt,
            image_hash=image_hash,
        )

        upload_again = SimpleUploadedFile(
            'r.jpg',
            JPEG_BYTES_DUPLICATE,
            content_type='image/jpeg',
        )
        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_pending_receipt',
        ) as task_mock:
            response = self.client.post(
                reverse('receipts:upload'),
                {'file': upload_again, 'account': self.account.pk},
            )

        self.assertRedirects(response, reverse('receipts:list'))
        self.assertFalse(
            PendingReceipt.objects.filter(user=self.user).exists(),
        )
        task_mock.delay.assert_not_called()

    def test_upload_rejects_corrupt_image_before_dispatch(self) -> None:
        upload = SimpleUploadedFile(
            'r.jpg',
            b'\xff\xd8\xff\xe0sample-bytes',
            content_type='image/jpeg',
        )
        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_pending_receipt',
        ) as task_mock:
            response = self.client.post(
                reverse('receipts:upload'),
                {'file': upload, 'account': self.account.pk},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            PendingReceipt.objects.filter(user=self.user).exists(),
        )
        task_mock.delay.assert_not_called()


class PendingCounterViewTests(TestCase):
    """Counter endpoint returns the live processing count for the user."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='counter-user',
            password='pass',  # nosec B106: test-only password
            email='c@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_counter_reflects_processing_count(self) -> None:
        service: PendingReceiptService = (
            ApplicationContainer().receipts.pending_receipt_service()
        )
        for index in range(2):
            upload = SimpleUploadedFile(
                f'r{index}.jpg',
                f'bytes-{index}'.encode(),
                content_type='image/jpeg',
            )
            service.create_processing_job(
                user=self.user,
                account=self.account,
                image_file=upload,
                image_hash=compute_image_hash(upload),
            )

        response = self.client.get(reverse('receipts:pending_counter'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2')

    def test_counter_empty_renders_no_badge(self) -> None:
        response = self.client.get(reverse('receipts:pending_counter'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'animate-spin')


class PendingRetryViewTests(TestCase):
    """Retry view re-queues a failed pending row using the saved file."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='retry-user',
            password='pass',  # nosec B106: test-only password
            email='r@example.com',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=1000,
            currency='RU',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_retry_resets_failed_pending(self) -> None:
        service: PendingReceiptService = (
            ApplicationContainer().receipts.pending_receipt_service()
        )
        upload = SimpleUploadedFile(
            'r.jpg',
            b'bytes',
            content_type='image/jpeg',
        )
        pending = service.create_processing_job(
            user=self.user,
            account=self.account,
            image_file=upload,
            image_hash=compute_image_hash(upload),
        )
        service.mark_failed(
            pending_receipt=pending,
            error_message='nope',
        )

        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_pending_receipt',
        ) as task_mock:
            task_mock.delay.return_value = mock.Mock(id='task-id-2')
            response = self.client.post(
                reverse('receipts:pending_retry', args=[pending.pk]),
            )

        self.assertRedirects(response, reverse('receipts:list'))
        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingReceiptStatus.PROCESSING)
        self.assertEqual(pending.error_message, '')
        task_mock.delay.assert_called_once_with(pending.pk)
