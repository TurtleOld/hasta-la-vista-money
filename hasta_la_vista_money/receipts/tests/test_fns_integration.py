"""Tests for FNS QR receipt integration."""

from __future__ import annotations

import io
import sys
import types
from typing import Any, Self
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    PendingReceipt,
    PendingReceiptStatus,
    Product,
)
from hasta_la_vista_money.receipts.services.category_classifier import (
    DEFAULT_PRODUCT_CATEGORY,
    ReceiptItemCategoryService,
    normalize_product_name,
)
from hasta_la_vista_money.receipts.services.fns_client import (
    FNSClient,
    FNSCredentials,
    FNSMalformedResponseError,
    FNSRateLimitError,
    FNSTimeoutError,
    FNSUnauthorizedError,
)
from hasta_la_vista_money.receipts.services.fns_mapper import (
    map_fns_receipt_to_receipt_data,
)
from hasta_la_vista_money.receipts.services.fns_qr import (
    QRCodeExtractor,
    QRCodeNotFoundError,
    parse_fns_qr,
)
from hasta_la_vista_money.receipts.services.fns_session_cache import (
    FNSSession,
    FNSSessionCache,
)
from hasta_la_vista_money.receipts.services.pending_receipt_service import (
    PendingReceiptService,
    compute_image_hash,
)
from hasta_la_vista_money.receipts.tasks import process_pending_receipt
from hasta_la_vista_money.users.models import User

TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'fns-tests',
    },
}
HTTP_OK = 200
HTTP_REDIRECT_MAX = 300


def _fns_payload(*, retail_place: str | None = 'Магазин') -> dict[str, Any]:
    return {
        'document': {
            'receipt': {
                'retailPlace': retail_place,
                'retailPlaceAddress': 'Москва, ул. Тестовая, 1',
                'user': 'ООО Ромашка',
                'totalSum': 12345,
                'operationType': 1,
                'dateTime': 1_717_238_160,
                'fiscalDocumentNumber': 77,
                'nds10': 0,
                'nds20': 2058,
                'items': [
                    {
                        'name': 'Товар',
                        'price': 12345,
                        'quantity': 1,
                        'sum': 12345,
                    },
                ],
            },
        },
    }


def _fake_payload() -> dict[str, Any]:
    return {
        'name_seller': 'OCR Shop',
        'retail_place_address': 'Address',
        'retail_place': 'Place',
        'total_sum': 123.45,
        'operation_type': 1,
        'receipt_date': timezone.now().strftime('%d.%m.%Y %H:%M'),
        'number_receipt': 42,
        'nds10': 0,
        'nds20': 0,
        'items': [
            {
                'product_name': 'Item',
                'category': 'Misc',
                'price': 123.45,
                'quantity': 1,
                'amount': 123.45,
            },
        ],
    }


class FNSQRTests(TestCase):
    """QR parsing and extraction."""

    def test_parse_fns_qr_requires_fiscal_fields(self) -> None:
        parsed = parse_fns_qr(
            't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1',
        )

        self.assertEqual(parsed.fn, '1')
        self.assertEqual(parsed.fiscal_key, '1:2:3:1')

    def test_extract_reads_first_valid_qr(self) -> None:
        image_bytes = io.BytesIO()
        Image.new('RGB', (1, 1), 'white').save(image_bytes, format='PNG')
        upload = SimpleUploadedFile(
            'qr.png',
            image_bytes.getvalue(),
            content_type='image/png',
        )
        pyzbar_package = types.ModuleType('pyzbar')
        pyzbar_module = types.ModuleType('pyzbar.pyzbar')
        pyzbar_module.ZBarSymbol = types.SimpleNamespace(QRCODE='QRCODE')
        pyzbar_module.decode = mock.Mock(
            return_value=[
                types.SimpleNamespace(
                    data=b't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1',
                ),
            ],
        )

        with mock.patch.dict(
            sys.modules,
            {'pyzbar': pyzbar_package, 'pyzbar.pyzbar': pyzbar_module},
        ):
            parsed = QRCodeExtractor().extract(upload)

        self.assertEqual(parsed.i, '2')

    def test_extract_raises_when_qr_missing(self) -> None:
        image_bytes = io.BytesIO()
        Image.new('RGB', (1, 1), 'white').save(image_bytes, format='PNG')
        upload = SimpleUploadedFile(
            'qr.png',
            image_bytes.getvalue(),
            content_type='image/png',
        )
        pyzbar_package = types.ModuleType('pyzbar')
        pyzbar_module = types.ModuleType('pyzbar.pyzbar')
        pyzbar_module.ZBarSymbol = types.SimpleNamespace(QRCODE='QRCODE')
        pyzbar_module.decode = mock.Mock(return_value=[])

        with (
            mock.patch.dict(
                sys.modules,
                {'pyzbar': pyzbar_package, 'pyzbar.pyzbar': pyzbar_module},
            ),
            self.assertRaises(QRCodeNotFoundError),
        ):
            QRCodeExtractor().extract(upload)


class FNSMapperTests(TestCase):
    """FNS JSON mapper."""

    def test_maps_money_kopecks_and_retail_place(self) -> None:
        mapped = map_fns_receipt_to_receipt_data(_fns_payload())

        self.assertEqual(mapped['name_seller'], 'Магазин')
        self.assertEqual(mapped['total_sum'], '123.45')
        self.assertEqual(mapped['nds20'], '20.58')
        self.assertEqual(mapped['items'][0]['price'], '123.45')
        self.assertEqual(mapped['items'][0]['amount'], '123.45')

    def test_uses_legal_name_when_retail_place_empty(self) -> None:
        mapped = map_fns_receipt_to_receipt_data(
            _fns_payload(retail_place=''),
        )

        self.assertEqual(mapped['name_seller'], 'ООО Ромашка')
        self.assertIsNone(mapped['retail_place'])


class ReceiptItemCategoryServiceTests(TestCase):
    """Receipt item category classifier."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='category-user',
            password='pass',  # nosec B106: test-only password
            email='category@example.com',
        )
        self.service = ReceiptItemCategoryService()

    def test_normalizes_product_name(self) -> None:
        self.assertEqual(
            normalize_product_name('Кефир ЗДРАВУШКА 1%'),
            'кефир здравушка 1',
        )

    def test_uses_user_history_before_rules(self) -> None:
        Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка',
            category='Завтраки',
        )

        category = self.service.categorize(
            user=self.user,
            product_name='кефир здравушка',
        )

        self.assertEqual(category, 'Завтраки')

    def test_uses_rules_when_history_missing(self) -> None:
        self.assertEqual(
            self.service.categorize(user=self.user, product_name='Томаты'),
            'Овощи',
        )

    def test_falls_back_to_default_category(self) -> None:
        self.assertEqual(
            self.service.categorize(user=self.user, product_name='XYZ 123'),
            DEFAULT_PRODUCT_CATEGORY,
        )


@override_settings(CACHES=TEST_CACHES)
class FNSSessionCacheTests(TestCase):
    """FNS session cache storage."""

    def setUp(self) -> None:
        cache.clear()

    def test_stores_and_reads_session_from_cache(self) -> None:
        session_cache = FNSSessionCache()

        session_cache.set(
            FNSSession(
                session_id='session-id',
                refresh_token='refresh-token',  # nosec B106: test-only token
            ),
        )

        self.assertEqual(
            session_cache.get(),
            FNSSession('session-id', 'refresh-token'),  # nosec B106
        )

    def test_clear_removes_session(self) -> None:
        session_cache = FNSSessionCache()
        session_cache.set(FNSSession(session_id='session-id'))

        session_cache.clear()

        self.assertIsNone(session_cache.get())


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._json_error = json_error

    @property
    def is_success(self) -> bool:
        return HTTP_OK <= self.status_code < HTTP_REDIRECT_MAX

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class _FakeHTTPClient:
    responses: list[_FakeResponse] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def request(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        return self.responses.pop(0)


@override_settings(CACHES=TEST_CACHES)
class FNSClientTests(TestCase):
    """FNS client errors and session handling."""

    def setUp(self) -> None:
        cache.clear()
        _FakeHTTPClient.responses = []
        self.credentials = FNSCredentials(
            inn='123456789012',
            password='password',  # nosec B106: test-only password
            client_secret='secret',  # nosec B106: test-only secret
        )

    def _client(self) -> FNSClient:
        return FNSClient(
            http_client_factory=_FakeHTTPClient,
            base_url='https://fns.example/v2',
            credentials=self.credentials,
            timeout_seconds=1,
            poll_attempts=1,
            poll_interval_seconds=0,
        )

    def test_fetch_receipt_authenticates_and_caches_session(self) -> None:
        _FakeHTTPClient.responses = [
            _FakeResponse(
                payload={
                    'sessionId': 'session-id',
                    'refresh_token': 'refresh',  # nosec B105
                },
            ),
            _FakeResponse(payload={'id': 'ticket-id'}),
            _FakeResponse(payload=_fns_payload()),
        ]

        payload = self._client().fetch_receipt('qr')

        self.assertIn('document', payload)
        self.assertEqual(
            FNSSessionCache().get(),
            FNSSession('session-id', 'refresh'),
        )

    def test_reauthenticates_after_unauthorized_session(self) -> None:
        FNSSessionCache().set(FNSSession(session_id='expired'))
        _FakeHTTPClient.responses = [
            _FakeResponse(status_code=401),
            _FakeResponse(payload={'sessionId': 'fresh'}),
            _FakeResponse(payload={'id': 'ticket-id'}),
            _FakeResponse(payload=_fns_payload()),
        ]

        payload = self._client().fetch_receipt('qr')

        self.assertIn('document', payload)
        self.assertEqual(FNSSessionCache().get(), FNSSession('fresh'))

    def test_raises_rate_limit(self) -> None:
        _FakeHTTPClient.responses = [
            _FakeResponse(payload={'sessionId': 'session-id'}),
            _FakeResponse(status_code=429),
        ]

        with self.assertRaises(FNSRateLimitError):
            self._client().fetch_receipt('qr')

    def test_raises_timeout_when_ticket_has_no_receipt(self) -> None:
        _FakeHTTPClient.responses = [
            _FakeResponse(payload={'sessionId': 'session-id'}),
            _FakeResponse(payload={'id': 'ticket-id'}),
            _FakeResponse(payload={'status': 'processing'}),
        ]

        with self.assertRaises(FNSTimeoutError):
            self._client().fetch_receipt('qr')

    def test_raises_malformed_json(self) -> None:
        _FakeHTTPClient.responses = [
            _FakeResponse(json_error=ValueError('bad json')),
        ]

        with self.assertRaises(FNSMalformedResponseError):
            self._client().fetch_receipt('qr')

    def test_raises_unauthorized_for_direct_private_call(self) -> None:
        _FakeHTTPClient.responses = [_FakeResponse(status_code=401)]

        with self.assertRaises(FNSUnauthorizedError):
            self._client()._create_ticket(FNSSession('bad'), 'qr')


@override_settings(
    CACHES=TEST_CACHES,
    FNS_INN='123456789012',
    FNS_PASSWORD='password',  # nosec B106: test-only password
    FNS_CLIENT_SECRET='secret',  # nosec B106: test-only secret
    FNS_POLL_INTERVAL_SECONDS=0,
)
class ProcessPendingReceiptFNSTests(TestCase):
    """Celery pending flow through FNS-first pipeline."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='fns-user',
            password='pass',  # nosec B106: test-only password
            email='fns@example.com',
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

    def test_task_marks_ready_from_fns(self) -> None:
        pending = self._create_pending()
        with (
            mock.patch(
                'hasta_la_vista_money.receipts.tasks.QRCodeExtractor.extract',
                return_value=parse_fns_qr(
                    't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1',
                ),
            ),
            mock.patch(
                'hasta_la_vista_money.receipts.tasks.FNSClient.fetch_receipt',
                return_value=_fns_payload(),
            ),
        ):
            process_pending_receipt(pending.pk)

        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingReceiptStatus.READY)
        self.assertEqual(pending.receipt_data['name_seller'], 'Магазин')
        self.assertEqual(
            pending.receipt_data['items'][0]['category'],
            DEFAULT_PRODUCT_CATEGORY,
        )
        self.assertIn('_fns_raw', pending.receipt_data)

    def test_task_applies_history_category_to_fns_items(self) -> None:
        Product.objects.create(
            user=self.user,
            product_name='Товар',
            category='История',
        )
        pending = self._create_pending()
        with (
            mock.patch(
                'hasta_la_vista_money.receipts.tasks.QRCodeExtractor.extract',
                return_value=parse_fns_qr(
                    't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1',
                ),
            ),
            mock.patch(
                'hasta_la_vista_money.receipts.tasks.FNSClient.fetch_receipt',
                return_value=_fns_payload(),
            ),
        ):
            process_pending_receipt(pending.pk)

        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingReceiptStatus.READY)
        self.assertEqual(
            pending.receipt_data['items'][0]['category'],
            'История',
        )

    def test_task_marks_failed_when_qr_missing(self) -> None:
        pending = self._create_pending()
        with mock.patch(
            'hasta_la_vista_money.receipts.tasks.QRCodeExtractor.extract',
            side_effect=QRCodeNotFoundError('no qr with fn=secret'),
        ):
            process_pending_receipt(pending.pk)

        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingReceiptStatus.FAILED)
        self.assertIn('QR-код', pending.error_message)
        self.assertNotIn('fn=secret', pending.error_message)
