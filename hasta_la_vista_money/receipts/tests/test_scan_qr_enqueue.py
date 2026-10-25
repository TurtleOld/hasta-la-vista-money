"""Tests for queuing a camera-scanned QR and its API endpoint."""

from decimal import Decimal
from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Receipt,
    ReceiptProcessingLog,
    ReceiptProcessingStatus,
)
from hasta_la_vista_money.users.models import User

_RAW_QR = 't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1'
_SEND_TASK = (
    'hasta_la_vista_money.receipts.services.receipt_processing_service.'
    'current_app.send_task'
)


class EnqueueScannedQRServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='scan-service-user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.service = (
            ApplicationContainer().receipts.receipt_processing_service()
        )

    def test_new_qr_is_queued(self) -> None:
        with mock.patch(_SEND_TASK) as task_mock:
            outcome = self.service.enqueue_scanned_qr(
                user=self.user,
                account=self.account,
                qr_raw=_RAW_QR,
            )

        self.assertEqual(outcome.status, 'queued')
        log = ReceiptProcessingLog.objects.get(user=self.user)
        self.assertEqual(log.status, ReceiptProcessingStatus.PROCESSING)
        self.assertEqual(log.qr_raw, _RAW_QR)
        task_mock.assert_called_once_with(
            constants.RECEIPT_PROCESSING_LOG_TASK_NAME,
            args=[log.pk],
            task_id=log.task_id,
        )

    def test_saved_receipt_is_duplicate_with_link_target(self) -> None:
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            receipt_date=timezone.now(),
            total_sum=Decimal('123.45'),
            fiscal_key='1:2:3:1',
        )

        with mock.patch(_SEND_TASK) as task_mock:
            outcome = self.service.enqueue_scanned_qr(
                user=self.user,
                account=self.account,
                qr_raw=_RAW_QR,
            )

        self.assertEqual(outcome.status, 'duplicate')
        self.assertEqual(outcome.duplicate, receipt)
        task_mock.assert_not_called()
        self.assertTrue(
            ReceiptProcessingLog.objects.get(user=self.user).is_duplicate,
        )

    def test_queue_failure_is_error(self) -> None:
        with (
            mock.patch(_SEND_TASK) as task_mock,
            mock.patch.object(
                self.service.processing_log_repository,
                'create_qr_job',
                side_effect=RuntimeError('db down'),
            ),
        ):
            outcome = self.service.enqueue_scanned_qr(
                user=self.user,
                account=self.account,
                qr_raw=_RAW_QR,
            )

        self.assertEqual(outcome.status, 'error')
        task_mock.assert_not_called()


class ScanQRAPITests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='scan-api-user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.url = reverse('receipts:scan_qr_api')

    def test_queued_scan_returns_status_and_message(self) -> None:
        with mock.patch(_SEND_TASK):
            response = self.client.post(
                self.url,
                {'qr_raw': _RAW_QR, 'account': self.account.pk},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'queued')
        self.assertTrue(response.json()['message'])
        self.assertTrue(
            ReceiptProcessingLog.objects.filter(user=self.user).exists(),
        )

    def test_duplicate_scan_links_saved_receipt(self) -> None:
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            receipt_date=timezone.now(),
            total_sum=Decimal('123.45'),
            fiscal_key='1:2:3:1',
        )

        response = self.client.post(
            self.url,
            {'qr_raw': _RAW_QR, 'account': self.account.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'duplicate')
        self.assertEqual(
            response.json()['url'],
            reverse('receipts:view', args=[receipt.pk]),
        )

    def test_duplicate_of_pending_log_links_receipts_list(self) -> None:
        ReceiptProcessingLog.objects.create(
            user=self.user,
            account=self.account,
            qr_raw=_RAW_QR,
            image_hash='a' * 64,
            fiscal_key='1:2:3:1',
        )

        response = self.client.post(
            self.url,
            {'qr_raw': _RAW_QR, 'account': self.account.pk},
        )

        self.assertEqual(response.json()['status'], 'duplicate')
        self.assertEqual(response.json()['url'], reverse('receipts:list'))

    def test_foreign_account_is_rejected(self) -> None:
        other = User.objects.create_user(username='scan-api-other')
        foreign = Account.objects.create(
            user=other,
            name_account='Foreign',
            balance=Decimal('1.00'),
            currency='RUB',
        )

        response = self.client.post(
            self.url,
            {'qr_raw': _RAW_QR, 'account': foreign.pk},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'error')
        self.assertFalse(ReceiptProcessingLog.objects.exists())

    def test_invalid_qr_is_rejected(self) -> None:
        response = self.client.post(
            self.url,
            {'qr_raw': 'not-a-receipt', 'account': self.account.pk},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'error')
        self.assertTrue(response.json()['message'])

    def test_queue_failure_returns_server_error(self) -> None:
        with mock.patch(
            'hasta_la_vista_money.receipts.repositories.'
            'receipt_processing_log_repository.'
            'ReceiptProcessingLogRepository.create_qr_job',
            side_effect=RuntimeError('db down'),
        ):
            response = self.client.post(
                self.url,
                {'qr_raw': _RAW_QR, 'account': self.account.pk},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(
            response.json()['message'],
            str(constants.ERROR_PROCESSING_RECEIPT),
        )

    def test_session_post_without_csrf_token_is_forbidden(self) -> None:
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            self.url,
            {'qr_raw': _RAW_QR, 'account': self.account.pk},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReceiptProcessingLog.objects.exists())

    def test_anonymous_request_is_rejected(self) -> None:
        response = Client().post(
            self.url,
            {'qr_raw': _RAW_QR, 'account': self.account.pk},
        )

        self.assertIn(response.status_code, (401, 403))
