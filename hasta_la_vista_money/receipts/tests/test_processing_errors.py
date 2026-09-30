"""Tests for receipt processing errors recorded in the processing journal."""

import hashlib
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Receipt,
    ReceiptProcessingErrorCode,
    ReceiptProcessingLog,
    ReceiptProcessingStage,
    ReceiptProcessingStatus,
)
from hasta_la_vista_money.receipts.services.fns_client import (
    FNSAuthenticationError,
    FNSRateLimitError,
    FNSTemporaryUnavailableError,
    FNSUnauthorizedError,
)
from hasta_la_vista_money.receipts.tasks import (
    cleanup_stale_receipt_processing_logs,
    process_receipt_processing_log,
)
from hasta_la_vista_money.receipts.validators.parsed_receipt import (
    ReceiptParseValidationError,
)
from hasta_la_vista_money.users.models import User

_TASKS = 'hasta_la_vista_money.receipts.tasks'
_RAW_QR = 't=20260525T1200&s=120.00&fn=1&i=2&fp=3&n=1'


def _receipt_data(**overrides: Any) -> dict[str, Any]:
    item = {
        'product_name': 'Item',
        'category': 'Misc',
        'price': '120.00',
        'quantity': '1',
        'amount': '120.00',
    }
    item.update(overrides.pop('item', {}))
    data: dict[str, Any] = {
        'name_seller': 'Shop',
        'retail_place_address': 'Address',
        'retail_place': 'Place',
        'total_sum': '120.00',
        'operation_type': 1,
        'receipt_date': timezone.now().strftime('%d.%m.%Y %H:%M'),
        'number_receipt': 42,
        'nds10': '0.00',
        'nds20': '0.00',
        'items': [item],
    }
    data.update(overrides)
    return data


class _ProcessingLogCase(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='processing-error-user',
            password='pass',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RU',
        )

    def _log(self, **fields: Any) -> ReceiptProcessingLog:
        defaults: dict[str, Any] = {
            'user': self.user,
            'account': self.account,
            'qr_raw': _RAW_QR,
        }
        defaults.update(fields)
        return ReceiptProcessingLog.objects.create(**defaults)

    def _run(self, log: ReceiptProcessingLog) -> ReceiptProcessingLog:
        cast('Any', process_receipt_processing_log).apply(args=[log.pk])
        log.refresh_from_db()
        return log

    def assert_failed_at(
        self,
        log: ReceiptProcessingLog,
        code: ReceiptProcessingErrorCode,
        stage: ReceiptProcessingStage | str,
    ) -> None:
        self.assertEqual(log.status, ReceiptProcessingStatus.FAILED)
        self.assertEqual(
            (log.error_code, log.error_stage),
            (code, stage),
        )
        self.assertNotEqual(log.error_message, '')


class ProcessingErrorStageTests(_ProcessingLogCase):
    """Each pipeline stage records its own code and stage in the journal."""

    def test_missing_source_fails_at_qr_stage(self) -> None:
        log = self._run(self._log(qr_raw=''))

        self.assert_failed_at(
            log,
            ReceiptProcessingErrorCode.IMAGE_MISSING,
            ReceiptProcessingStage.QR,
        )

    def test_unreadable_qr_fails_at_qr_stage(self) -> None:
        log = self._run(self._log(qr_raw='not-a-receipt-qr'))

        self.assert_failed_at(
            log,
            ReceiptProcessingErrorCode.QR_INVALID,
            ReceiptProcessingStage.QR,
        )

    def test_rejected_credentials_fail_at_fns_stage_without_retry(
        self,
    ) -> None:
        with mock.patch(f'{_TASKS}.FNSClient') as client:
            client.return_value.fetch_receipt.side_effect = (
                FNSAuthenticationError('rejected')
            )
            log = self._run(self._log())

        self.assert_failed_at(
            log,
            ReceiptProcessingErrorCode.FNS_AUTH_FAILED,
            ReceiptProcessingStage.FNS,
        )
        client.return_value.fetch_receipt.assert_called_once()

    def test_unauthorized_session_is_final_auth_failure(self) -> None:
        with mock.patch(f'{_TASKS}.FNSClient') as client:
            client.return_value.fetch_receipt.side_effect = (
                FNSUnauthorizedError('unauthorized')
            )
            log = self._run(self._log())

        self.assert_failed_at(
            log,
            ReceiptProcessingErrorCode.FNS_AUTH_FAILED,
            ReceiptProcessingStage.FNS,
        )

    def test_unmappable_fns_response_fails_at_map_stage(self) -> None:
        with mock.patch(f'{_TASKS}.FNSClient') as client:
            client.return_value.fetch_receipt.return_value = {}
            log = self._run(self._log())

        self.assert_failed_at(
            log,
            ReceiptProcessingErrorCode.FNS_BAD_RESPONSE,
            ReceiptProcessingStage.MAP,
        )

    def test_invalid_receipt_keeps_validator_message(self) -> None:
        with (
            mock.patch(f'{_TASKS}.FNSClient'),
            mock.patch(
                f'{_TASKS}.map_fns_receipt_to_receipt_data',
                return_value=_receipt_data(),
            ),
            mock.patch(
                f'{_TASKS}.validate_receipt_parse_payload',
                side_effect=ReceiptParseValidationError(
                    'bad',
                    user_message='Сумма позиций не совпадает.',
                ),
            ),
        ):
            log = self._run(self._log())

        self.assert_failed_at(
            log,
            ReceiptProcessingErrorCode.RECEIPT_INVALID,
            ReceiptProcessingStage.VALIDATE,
        )
        self.assertEqual(log.error_message, 'Сумма позиций не совпадает.')

    def test_invalid_product_line_fails_at_create_stage(self) -> None:
        with mock.patch(
            f'{_TASKS}._run_processing_log_pipeline',
            return_value=_receipt_data(item={'price': '-1.00'}),
        ):
            log = self._run(self._log())

        self.assert_failed_at(
            log,
            ReceiptProcessingErrorCode.LINE_INVALID,
            ReceiptProcessingStage.CREATE,
        )
        self.assertIn('не прошёл проверку сумм', log.error_message)
        self.assertFalse(Receipt.objects.filter(user=self.user).exists())

    def test_non_positive_total_fails_at_create_stage(self) -> None:
        with mock.patch(
            f'{_TASKS}._run_processing_log_pipeline',
            return_value=_receipt_data(total_sum='0.00'),
        ):
            log = self._run(self._log())

        self.assert_failed_at(
            log,
            ReceiptProcessingErrorCode.TOTAL_INVALID,
            ReceiptProcessingStage.CREATE,
        )

    def test_cleanup_records_timeout_without_stage(self) -> None:
        log = self._log(
            task_id='stalled-task',
            processing_started_at=timezone.now() - timedelta(hours=1),
        )

        cleanup_stale_receipt_processing_logs()

        log.refresh_from_db()
        self.assert_failed_at(log, ReceiptProcessingErrorCode.TIMED_OUT, '')


class ProcessingDegradationTests(_ProcessingLogCase):
    """Auxiliary enrichment failures never block the receipt."""

    def test_categorization_failure_still_creates_receipt(self) -> None:
        with (
            mock.patch(f'{_TASKS}.FNSClient'),
            mock.patch(
                f'{_TASKS}.map_fns_receipt_to_receipt_data',
                return_value=_receipt_data(item={'category': ''}),
            ),
            mock.patch(
                f'{_TASKS}._get_receipt_item_category_service',
            ) as category_service,
        ):
            category_service.return_value.categorize_items.side_effect = (
                RuntimeError('classifier down')
            )
            log = self._run(self._log())

        self.assertEqual(log.status, ReceiptProcessingStatus.COMPLETED)
        receipt = Receipt.objects.get(user=self.user)
        category = receipt.product.get().category
        if category is None:
            self.fail('Product has no category')
        self.assertEqual(category.name, constants.DEFAULT_PRODUCT_CATEGORY)

    def test_seller_lookup_failure_still_creates_receipt(self) -> None:
        with (
            mock.patch(f'{_TASKS}.FNSClient'),
            mock.patch(
                f'{_TASKS}.map_fns_receipt_to_receipt_data',
                return_value=_receipt_data(inn='7700000000', retail_place=''),
            ),
            mock.patch(f'{_TASKS}.SellerRepository') as seller_repository,
        ):
            seller_repository.return_value.find_by_inn.side_effect = (
                RuntimeError('db hiccup')
            )
            log = self._run(self._log())

        self.assertEqual(log.status, ReceiptProcessingStatus.COMPLETED)


class ProcessingRetryTests(_ProcessingLogCase):
    """Temporary FNS errors are retried before becoming final."""

    def test_temporary_error_is_retried_until_success(self) -> None:
        journal_states: list[tuple[str, str]] = []

        def fetch(_raw_qr: str) -> dict[str, Any]:
            log = ReceiptProcessingLog.objects.get(user=self.user)
            journal_states.append((log.status, log.error_code))
            if len(journal_states) == 1:
                raise FNSTemporaryUnavailableError('down')
            return {}

        with (
            mock.patch(f'{_TASKS}.FNSClient') as client,
            mock.patch(
                f'{_TASKS}.map_fns_receipt_to_receipt_data',
                return_value=_receipt_data(),
            ),
        ):
            client.return_value.fetch_receipt.side_effect = fetch
            log = self._run(self._log())

        self.assertEqual(log.status, ReceiptProcessingStatus.COMPLETED)
        self.assertEqual(log.error_code, '')
        self.assertEqual(
            journal_states[1],
            (
                ReceiptProcessingStatus.PROCESSING,
                ReceiptProcessingErrorCode.FNS_UNAVAILABLE,
            ),
        )

    def test_temporary_error_becomes_final_after_retries(self) -> None:
        with mock.patch(f'{_TASKS}.FNSClient') as client:
            client.return_value.fetch_receipt.side_effect = FNSRateLimitError(
                'slow down',
            )
            log = self._run(self._log())

        self.assert_failed_at(
            log,
            ReceiptProcessingErrorCode.FNS_RATE_LIMITED,
            ReceiptProcessingStage.FNS,
        )
        self.assertEqual(
            client.return_value.fetch_receipt.call_count,
            constants.RECEIPT_PROCESSING_MAX_RETRIES + 1,
        )

    def test_retry_countdown_honours_retry_after(self) -> None:
        with (
            mock.patch(f'{_TASKS}.FNSClient') as client,
            mock.patch.object(
                process_receipt_processing_log,
                'retry',
                side_effect=RuntimeError('stop'),
            ) as retry,
        ):
            client.return_value.fetch_receipt.side_effect = FNSRateLimitError(
                'slow down',
                retry_after=90,
            )
            self._run(self._log())

        self.assertEqual(retry.call_args.kwargs['countdown'], 90)


class ProcessingErrorLoggingTests(_ProcessingLogCase):
    """A failure is logged once with enough context to find the receipt."""

    def test_line_failure_logs_context_without_product_name(self) -> None:
        log = self._log(fiscal_key='1:2:3:1')
        with (
            mock.patch(
                f'{_TASKS}._run_processing_log_pipeline',
                return_value=_receipt_data(
                    item={'price': '-1.00', 'product_name': 'Secret'},
                ),
            ),
            mock.patch(f'{_TASKS}.logger') as logger,
        ):
            self._run(log)

        failures = [
            call
            for call in logger.warning.call_args_list
            if call.args == ('receipt_processing_failed',)
        ]
        self.assertEqual(len(failures), 1)
        fields = failures[0].kwargs
        self.assertEqual(fields['processing_log_id'], log.pk)
        self.assertEqual(fields['user_id'], self.user.pk)
        self.assertEqual(fields['fiscal_key'], '1:2:3:1')
        self.assertEqual(fields['error_code'], 'line_invalid')
        self.assertEqual(fields['error_stage'], 'create')
        self.assertEqual(fields['line_index'], 0)
        self.assertEqual(fields['line_price'], '-1.00')
        self.assertIsInstance(fields['exc_info'], ValueError)
        self.assertNotIn('Secret', repr(fields))

    def test_stale_task_outcome_is_discarded(self) -> None:
        log = self._log(task_id='newer-task')
        with (
            mock.patch(
                f'{_TASKS}._run_processing_log_pipeline',
                side_effect=RuntimeError('boom'),
            ),
            mock.patch(f'{_TASKS}.logger') as logger,
        ):
            self._run(log)

        self.assertEqual(log.status, ReceiptProcessingStatus.PROCESSING)
        events = [call.args[0] for call in logger.info.call_args_list]
        self.assertIn('receipt_processing_outcome_discarded', events)


class ProcessingLogDeleteAndReuploadTests(_ProcessingLogCase):
    """A failed journal entry never blocks entering the same receipt."""

    def setUp(self) -> None:
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)

    def test_failed_log_can_be_deleted_with_its_image(self) -> None:
        log = self._log(
            status=ReceiptProcessingStatus.FAILED,
            image_file=SimpleUploadedFile('r.jpg', b'img'),
        )
        storage = log.image_file.storage
        image_name = log.image_file.name

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('receipts:processing_delete', args=[log.pk]),
            )

        self.assertRedirects(response, reverse('receipts:list'))
        self.assertFalse(
            ReceiptProcessingLog.objects.filter(pk=log.pk).exists(),
        )
        self.assertFalse(storage.exists(image_name))

    def test_processing_log_cannot_be_deleted(self) -> None:
        log = self._log()

        self.client.post(reverse('receipts:processing_delete', args=[log.pk]))

        self.assertTrue(ReceiptProcessingLog.objects.filter(pk=log.pk).exists())

    def test_rescan_after_failure_replaces_failed_log(self) -> None:
        failed = self._log(
            status=ReceiptProcessingStatus.FAILED,
            image_hash=hashlib.sha256(_RAW_QR.encode()).hexdigest(),
            fiscal_key='1:2:3:1',
        )
        with mock.patch(
            'hasta_la_vista_money.receipts.views.process_receipt_processing_log',
        ):
            self.client.post(
                reverse('receipts:scan_qr'),
                {'qr_raw': _RAW_QR, 'account': self.account.pk},
            )

        self.assertFalse(
            ReceiptProcessingLog.objects.filter(pk=failed.pk).exists(),
        )
        log = ReceiptProcessingLog.objects.get(user=self.user)
        self.assertEqual(log.status, ReceiptProcessingStatus.PROCESSING)

    def test_failed_card_links_issue_tracker_only_for_app_errors(self) -> None:
        self._log(
            status=ReceiptProcessingStatus.FAILED,
            error_code=ReceiptProcessingErrorCode.LINE_INVALID,
            error_message='Чек получен из ФНС, но не прошёл проверку сумм.',
        )
        self._log(
            status=ReceiptProcessingStatus.FAILED,
            qr_raw='other',
            error_code=ReceiptProcessingErrorCode.QR_NOT_FOUND,
            error_message='QR не найден.',
        )

        response = self.client.get(reverse('receipts:list'))

        self.assertContains(response, constants.ISSUE_TRACKER_URL, count=1)
