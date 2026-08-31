"""Tests for automatic receipt processing through the processing log."""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Receipt,
    ReceiptProcessingLog,
    ReceiptProcessingStatus,
    Seller,
)
from hasta_la_vista_money.receipts.repositories import ProductCategoryRepository
from hasta_la_vista_money.receipts.tasks import (
    cleanup_stale_receipt_processing_logs,
    process_receipt_processing_log,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User


def _payload() -> dict[str, Any]:
    return {
        'name_seller': 'Shop',
        'retail_place_address': 'Address',
        'retail_place': 'Place',
        'total_sum': '120.00',
        'operation_type': 1,
        'receipt_date': timezone.now().strftime('%d.%m.%Y %H:%M'),
        'number_receipt': 42,
        'nds10': '0.00',
        'nds20': '0.00',
        'items': [
            {
                'product_name': 'Item',
                'category': 'Misc',
                'price': '100.00',
                'quantity': '1.00',
                'amount': '100.00',
            },
        ],
    }


class ReceiptProcessingLogTaskTests(TestCase):
    """A parsed FNS receipt is saved without a review step."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='processing-log-user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RU',
        )

    def test_task_creates_receipt_and_marks_adjustment_for_attention(
        self,
    ) -> None:
        log = ReceiptProcessingLog.objects.create(
            user=self.user,
            account=self.account,
            image_hash='a' * 64,
            fiscal_key='1:2:3:1',
        )

        with mock.patch(
            'hasta_la_vista_money.receipts.tasks._run_processing_log_pipeline',
            return_value=_payload(),
        ):
            process_receipt_processing_log(log.pk)

        log.refresh_from_db()
        receipt = Receipt.objects.get(user=self.user)
        self.assertEqual(log.status, ReceiptProcessingStatus.COMPLETED)
        self.assertEqual(log.receipt_id, receipt.pk)
        self.assertEqual(receipt.account_id, self.account.pk)
        self.assertEqual(receipt.adjustment, Decimal('20.00'))
        self.assertTrue(receipt.requires_attention)
        self.assertEqual(
            receipt.attention_reason,
            'Сумма товарных строк не совпадает с итоговой суммой чека.',
        )

    def test_task_records_fns_failure_without_creating_receipt(self) -> None:
        log = ReceiptProcessingLog.objects.create(
            user=self.user,
            account=self.account,
            qr_raw='t=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1',
            image_hash='b' * 64,
            fiscal_key='1:2:3:1',
        )

        with mock.patch(
            'hasta_la_vista_money.receipts.tasks._run_processing_log_pipeline',
            side_effect=ConnectionError,
        ):
            process_receipt_processing_log(log.pk)

        log.refresh_from_db()
        self.assertEqual(log.status, ReceiptProcessingStatus.FAILED)
        self.assertNotEqual(log.error_message, '')
        self.assertFalse(Receipt.objects.filter(user=self.user).exists())

    def test_task_conducts_receipt_when_account_balance_is_insufficient(
        self,
    ) -> None:
        self.account.balance = Decimal('10.00')
        self.account.save(update_fields=['balance'])
        log = ReceiptProcessingLog.objects.create(
            user=self.user,
            account=self.account,
            image_hash='d' * 64,
            fiscal_key='1:2:3:1',
        )
        with mock.patch(
            'hasta_la_vista_money.receipts.tasks._run_processing_log_pipeline',
            return_value=_payload(),
        ):
            process_receipt_processing_log(log.pk)

        log.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(log.status, ReceiptProcessingStatus.COMPLETED)
        self.assertEqual(self.account.balance, Decimal('-110.00'))


class ReceiptProcessingLogCleanupTaskTests(TestCase):
    """Stalled processing attempts remain retryable through the journal."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='processing-log-cleanup-user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RU',
        )

    def test_cleanup_marks_stalled_log_as_failed(self) -> None:
        log = ReceiptProcessingLog.objects.create(
            user=self.user,
            account=self.account,
            task_id='stalled-task',
            processing_started_at=timezone.now() - timedelta(hours=1),
        )

        result = cleanup_stale_receipt_processing_logs()

        log.refresh_from_db()
        self.assertEqual(result['recovered'], 1)
        self.assertEqual(log.status, ReceiptProcessingStatus.FAILED)
        self.assertNotEqual(log.error_message, '')


class ReceiptProcessingLogScanViewTests(TestCase):
    """Scanning keeps the user on the scanner and queues a journal entry."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='scan-processing-log-user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RU',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_scan_queues_log_and_returns_to_scanner(self) -> None:
        raw_qr = 't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1'
        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_receipt_processing_log',
        ) as task_mock:
            response = self.client.post(
                reverse('receipts:scan_qr'),
                {'qr_raw': raw_qr, 'account': self.account.pk},
            )

        self.assertRedirects(response, reverse('receipts:upload'))
        log = ReceiptProcessingLog.objects.get(user=self.user)
        self.assertEqual(log.status, ReceiptProcessingStatus.PROCESSING)
        self.assertEqual(log.account_id, self.account.pk)
        self.assertEqual(log.qr_raw, raw_qr)
        task_mock.apply_async.assert_called_once_with(
            args=[log.pk],
            task_id=log.task_id,
        )

    def test_repeat_scan_is_saved_as_duplicate_processing_log(self) -> None:
        raw_qr = 't=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1'
        ReceiptProcessingLog.objects.create(
            user=self.user,
            account=self.account,
            qr_raw=raw_qr,
            image_hash='a' * 64,
            fiscal_key='1:2:3:1',
        )

        response = self.client.post(
            reverse('receipts:scan_qr'),
            {'qr_raw': raw_qr, 'account': self.account.pk},
        )

        self.assertRedirects(response, reverse('receipts:upload'))
        duplicate_log = ReceiptProcessingLog.objects.filter(
            user=self.user,
            status=ReceiptProcessingStatus.DUPLICATE,
        ).get()
        self.assertTrue(duplicate_log.is_duplicate)
        self.assertEqual(duplicate_log.fiscal_key, '1:2:3:1')

    def test_retry_requeues_failed_log(self) -> None:
        log = ReceiptProcessingLog.objects.create(
            user=self.user,
            account=self.account,
            status=ReceiptProcessingStatus.FAILED,
            qr_raw='t=20260525T1200&s=123.45&fn=1&i=2&fp=3&n=1',
            image_hash='c' * 64,
            error_message='ФНС недоступна',
        )
        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_receipt_processing_log',
        ) as task_mock:
            response = self.client.post(
                reverse('receipts:processing_retry', args=[log.pk]),
            )

        self.assertRedirects(response, reverse('receipts:list'))
        log.refresh_from_db()
        self.assertEqual(log.status, ReceiptProcessingStatus.PROCESSING)
        self.assertEqual(log.error_message, '')
        task_mock.apply_async.assert_called_once_with(
            args=[log.pk],
            task_id=log.task_id,
        )

    def test_notifications_return_link_to_completed_receipt(self) -> None:
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            receipt_date=timezone.now(),
            total_sum=Decimal('10.00'),
        )
        log = ReceiptProcessingLog.objects.create(
            user=self.user,
            account=self.account,
            status=ReceiptProcessingStatus.COMPLETED,
            receipt=receipt,
        )

        response = self.client.get(reverse('receipts:processing_notifications'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['notifications']), 1)
        self.assertEqual(
            payload['notifications'][0]['url'],
            reverse('receipts:view', args=[receipt.pk]),
        )
        log.refresh_from_db()
        self.assertIsNotNone(log.notified_at)

    def test_list_polls_until_processed_receipt_appears(self) -> None:
        log = ReceiptProcessingLog.objects.create(
            user=self.user,
            account=self.account,
        )

        response = self.client.get(reverse('receipts:list'))

        self.assertContains(response, 'hx-trigger="every 5s"')

        seller = Seller.objects.create(
            user=self.user,
            name_seller='Finished receipt shop',
        )
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=seller,
            receipt_date=timezone.now(),
            total_sum=Decimal('10.00'),
        )
        log.status = ReceiptProcessingStatus.COMPLETED
        log.receipt = receipt
        log.save(update_fields=['status', 'receipt'])

        response = self.client.get(
            reverse('receipts:list'),
            HTTP_HX_REQUEST='true',
        )

        self.assertNotContains(response, 'hx-trigger="every 5s"')
        self.assertContains(
            response,
            reverse('receipts:view', args=[receipt.pk]),
        )

    def test_editing_automatic_receipt_clears_attention_when_fixed(
        self,
    ) -> None:
        seller = Seller.objects.create(user=self.user, name_seller='Shop')
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=seller,
            receipt_date=timezone.now(),
            number_receipt=1,
            operation_type=1,
            total_sum=Decimal('120.00'),
            adjustment=Decimal('20.00'),
            requires_attention=True,
            attention_reason=(
                'Сумма товарных строк не совпадает с итоговой суммой чека.'
            ),
            manual=False,
        )
        category = ProductCategoryRepository().get_or_create_category(
            user=self.user,
            name='Misc',
        )
        response = self.client.post(
            reverse('receipts:update', args=[receipt.pk]),
            {
                'seller': seller.pk,
                'retail_place': '',
                'account': self.account.pk,
                'receipt_date': timezone.localtime(
                    receipt.receipt_date,
                ).strftime('%Y-%m-%dT%H:%M'),
                'number_receipt': 1,
                'operation_type': 1,
                'nds10': '',
                'nds20': '',
                'total_sum': '120.00',
                'form-TOTAL_FORMS': '1',
                'form-INITIAL_FORMS': '0',
                'form-MIN_NUM_FORMS': '0',
                'form-MAX_NUM_FORMS': '1000',
                'form-0-product_name': 'Item',
                'form-0-category': category.pk,
                'form-0-price': '120.00',
                'form-0-quantity': '1.00',
                'form-0-amount': '120.00',
            },
        )

        self.assertEqual(response.status_code, 302)
        receipt.refresh_from_db()
        self.assertEqual(receipt.adjustment, Decimal('0.00'))
        self.assertFalse(receipt.requires_attention)
        self.assertEqual(receipt.attention_reason, '')

    def test_insufficient_funds_is_calculated_at_conducting_time(self) -> None:
        seller = Seller.objects.create(user=self.user, name_seller='Shop')
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=seller,
            receipt_date=timezone.now() - timedelta(days=1),
            operation_type=1,
            total_sum=Decimal('120.00'),
        )
        category = Category.objects.create(
            user=self.user,
            name='Income',
            type=TransactionType.INCOME,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.INCOME,
            amount=Decimal('200.00'),
            date=timezone.now(),
        )
        self.account.balance = Decimal('90.00')
        self.account.save(update_fields=['balance'])

        response = self.client.get(reverse('receipts:view', args=[receipt.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['insufficient_at_conducting'])
