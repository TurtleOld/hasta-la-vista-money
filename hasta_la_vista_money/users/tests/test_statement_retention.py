"""Retention setting and safe cleanup of bank statement data."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from typing import Final, cast
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.forms import UpdateUserForm
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    ReconciliationExpiredError,
)
from hasta_la_vista_money.users.services.bank_statement_retention import (
    BankStatementRetentionService,
)
from hasta_la_vista_money.users.services.profile import update_user_profile
from hasta_la_vista_money.users.services.statement_markup import (
    StatementMarkupConflictError,
)
from hasta_la_vista_money.users.services.statement_retention_policy import (
    row_has_bank_data,
)


def _form_data(user: User, days: object) -> dict[str, object]:
    return {
        'username': user.username,
        'email': user.email or 'user@example.com',
        'first_name': user.first_name,
        'last_name': user.last_name,
        'timezone_name': user.timezone_name,
        'statement_retention_days': days,
    }


class StatementRetentionSettingTest(TestCase):
    """The owner chooses a positive retention period for new uploads."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)

    def test_new_user_defaults_to_thirty_days(self) -> None:
        created = User.objects.create_user(username='retention-default')

        self.assertEqual(created.statement_retention_days, 30)

    def test_model_rejects_zero_and_negative_days(self) -> None:
        for value in (0, -1):
            self.user.statement_retention_days = value
            with self.assertRaises(ValidationError):
                self.user.full_clean()

    def test_model_rejects_non_representable_integer(self) -> None:
        self.user.statement_retention_days = 2_147_483_648

        with self.assertRaises(ValidationError):
            self.user.full_clean()

    def test_model_rejects_unrepresentable_deadline(self) -> None:
        self.user.statement_retention_days = 3_000_000

        with self.assertRaises(ValidationError):
            self.user.full_clean()

    def test_model_has_no_arbitrary_product_maximum(self) -> None:
        self.user.statement_retention_days = 36_500

        self.user.full_clean()
        self.assertEqual(self.user.statement_retention_days, 36_500)

    def test_form_accepts_positive_value_and_saves_it(self) -> None:
        form = UpdateUserForm(
            instance=self.user,
            data=_form_data(self.user, 14),
        )

        self.assertTrue(form.is_valid(), form.errors)
        user = update_user_profile(form)
        user.refresh_from_db()
        self.assertEqual(user.statement_retention_days, 14)

    def test_form_rejects_zero_and_overflow_without_saving(self) -> None:
        for value in (0, 2_147_483_648, 3_000_000):
            form = UpdateUserForm(
                instance=self.user,
                data=_form_data(self.user, value),
            )
            with self.subTest(days=value):
                self.assertFalse(form.is_valid())
                self.assertIn('statement_retention_days', form.errors)

        self.user.refresh_from_db()
        self.assertEqual(self.user.statement_retention_days, 30)

    def test_changing_setting_does_not_rewrite_existing_deadline(self) -> None:
        kept = timezone.now() + timedelta(days=3)
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=Account.objects.create(
                user=self.user,
                name_account='Банк',
                balance=Decimal('0.00'),
                currency='RUB',
            ),
            expires_at=kept,
        )
        self.user.statement_retention_days = 90
        self.user.save(update_fields=['statement_retention_days'])

        upload.refresh_from_db()
        self.assertEqual(upload.expires_at, kept)

    def test_new_upload_uses_current_setting(self) -> None:
        self.user.statement_retention_days = 7
        self.user.save(update_fields=['statement_retention_days'])
        account = Account.objects.create(
            user=self.user,
            name_account='Банк',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        client = Client()
        client.force_login(self.user)
        before = timezone.now()
        with patch(
            'hasta_la_vista_money.finance_account.bank_statement_views.'
            'process_bank_statement_task',
        ):
            response = client.post(
                reverse('finance_account:bank_statement_upload'),
                {
                    'account': account.pk,
                    'pdf_file': SimpleUploadedFile(
                        'statement.pdf',
                        b'%PDF-1.4 synthetic',
                        content_type='application/pdf',
                    ),
                },
            )
        after = timezone.now()

        self.assertEqual(response.status_code, 302)
        upload = BankStatementUpload.objects.get(account=account)
        self.assertGreaterEqual(upload.expires_at, before + timedelta(days=7))
        self.assertLessEqual(upload.expires_at, after + timedelta(days=7))

    def test_profile_shows_setting_and_reupload_hint(self) -> None:
        client = Client()
        client.force_login(self.user)

        response = client.get(
            reverse('users:profile', kwargs={'pk': self.user.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'statement_retention_days')
        self.assertContains(response, 'повторной загрузки')


class StatementRetentionCleanupTest(TestCase):
    """Cleanup removes bank details but keeps decisions and their trail."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Банк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        self.transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=timezone.now(),
            bank_calendar_date=date(2026, 4, 30),
            source_ref='movement-raw-ref',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            expires_at=timezone.now() - timedelta(seconds=1),
            statement_closing_balance=Decimal('1100.00'),
            account_balance_after=Decimal('1000.00'),
            balance_discrepancy=Decimal('100.00'),
            error_message='bank error with details',
            celery_task_id='celery-task',
            file_hash='file-hash',
        )
        self.upload.pdf_file.save(
            'statement.pdf',
            SimpleUploadedFile(
                'statement.pdf',
                b'%PDF-1.4 synthetic statement',
                content_type='application/pdf',
            ),
        )
        self.pdf_name = self.upload.pdf_file.name
        self.storage = self.upload.pdf_file.storage
        self.expires_at = self.upload.expires_at
        self.linked = self._row(
            1,
            BankStatementRow.Decision.LINKED,
            transaction=self.transaction,
        )
        self.pending = self._row(2, BankStatementRow.Decision.PENDING)
        self.deferred = self._row(
            3,
            BankStatementRow.Decision.DEFERRED,
        )
        self.excluded = self._row(
            4,
            BankStatementRow.Decision.EXCLUDED,
            reason='Оплата наличными',
        )
        self.expired = self._row(5, BankStatementRow.Decision.EXPIRED)
        BankStatementCandidate.objects.create(
            row=self.pending,
            transaction=self.transaction,
            description='Секретные детали кандидата',
            rank=0,
        )
        self.pending.candidate = self.transaction
        self.pending.save(update_fields=['candidate'])

    def _row(
        self,
        position: int,
        decision: str,
        *,
        reason: str = '',
        transaction: Transaction | None = None,
    ) -> BankStatementRow:
        row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('25.00'),
            bank_calendar_date=date(2026, 5, position),
            date_precision=BankStatementRow.DatePrecision.DAY,
            description='Секретное назначение',
            candidate_description='Секретный кандидат',
            suggested_category='Секретная категория',
            merchant_key='СЕКРЕТНЫЙ ПРОДАВЕЦ',
            counterparty_account='40817810000000000001',
            kind='card',
            source_ref=f'raw-{position}',
            source_ref_hash=f'{"a" * 63}{position}',
            source_ref_key_id='key-1',
            source_ref_version=1,
            source_identity_trusted=True,
            source_row_position=position,
            resume_decision=(
                BankStatementRow.Decision.PENDING
                if decision == BankStatementRow.Decision.DEFERRED
                else ''
            ),
            decision=decision,
            decision_reason=reason,
            transaction=transaction,
        )
        BankStatementDecisionAudit.objects.create(
            row=row,
            actor=self.user,
            decision=decision,
            reason=reason,
        )
        return row

    def _cleanup(self) -> int:
        container = ApplicationContainer()
        service = container.users.bank_statement_retention_service()
        with self.captureOnCommitCallbacks(execute=True):
            return int(service.cleanup_expired(self.upload.expires_at))

    def _scrubbed(self, row: BankStatementRow) -> None:
        self.assertIsNone(row.transaction_type)
        self.assertIsNone(row.transaction_date)
        self.assertIsNone(row.amount)
        self.assertIsNone(row.bank_calendar_date)
        self.assertEqual(row.date_precision, BankStatementRow.DatePrecision.DAY)
        self.assertEqual(row.description, '')
        self.assertEqual(row.candidate_description, '')
        self.assertEqual(row.suggested_category, '')
        self.assertEqual(row.merchant_key, '')
        self.assertEqual(row.counterparty_account, '')
        self.assertEqual(row.kind, '')
        self.assertIsNone(row.source_ref)
        self.assertIsNone(row.candidate)
        self.assertFalse(row.candidates.exists())
        self.assertIsNotNone(row.data_cleaned_at)

    def test_cleanup_preserves_decisions_positions_and_links(self) -> None:
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.account,
            amount=Decimal('250.00'),
            exchange_date=timezone.now(),
            bank_calendar_date=date(2026, 4, 28),
        )
        audit_count = AuditLog.objects.count()
        money_before = Transaction.objects.values_list(
            'pk',
            'amount',
            'date',
            'bank_calendar_date',
            'category_id',
        ).get(pk=self.transaction.pk)

        self.assertEqual(self._cleanup(), 1)

        for row in (
            self.linked,
            self.pending,
            self.deferred,
            self.excluded,
            self.expired,
        ):
            row.refresh_from_db()
            self._scrubbed(row)
            self.assertIsNotNone(row.source_row_position)
            self.assertIsNotNone(row.source_ref_hash)
            self.assertEqual(row.source_ref_key_id, 'key-1')
            self.assertEqual(row.source_ref_version, 1)
            self.assertTrue(row.source_identity_trusted)

        self.pending.refresh_from_db()
        self.deferred.refresh_from_db()
        self.excluded.refresh_from_db()
        self.expired.refresh_from_db()
        self.linked.refresh_from_db()
        self.assertEqual(
            self.pending.decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertEqual(
            self.deferred.decision,
            BankStatementRow.Decision.DEFERRED,
        )
        self.assertEqual(
            self.deferred.resume_decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertEqual(
            self.excluded.decision,
            BankStatementRow.Decision.EXCLUDED,
        )
        self.assertEqual(self.excluded.decision_reason, 'Оплата наличными')
        self.assertEqual(
            self.expired.decision,
            BankStatementRow.Decision.EXPIRED,
        )
        self.assertEqual(
            self.linked.decision,
            BankStatementRow.Decision.LINKED,
        )
        self.assertEqual(self.linked.transaction, self.transaction)
        for row in (
            self.linked,
            self.pending,
            self.deferred,
            self.excluded,
            self.expired,
        ):
            self.assertEqual(row.decision_audits.count(), 1)
        self.assertEqual(
            Transaction.objects.values_list(
                'pk',
                'amount',
                'date',
                'bank_calendar_date',
                'category_id',
            ).get(pk=self.transaction.pk),
            money_before,
        )
        transfer.refresh_from_db()
        self.assertEqual(transfer.bank_calendar_date, date(2026, 4, 28))
        self.assertEqual(transfer.amount, Decimal('250.00'))
        # The linked movement's audit held the legacy raw identifier: it is
        # anonymized in place and the scrub fact is the only new entry.
        self.assertEqual(AuditLog.objects.count(), audit_count + 1)
        scrub_fact = AuditLog.objects.get(
            model_name='users.BankStatementUpload',
            object_pk='statement-audit-scrub-v1',
        )
        self.assertEqual(
            scrub_fact.diff['bank_identifiers_anonymized']['new'],
            True,
        )
        self.assertFalse(
            AuditLog.objects.filter(
                model_name='transactions.Transaction',
                object_pk=str(self.transaction.pk),
                diff__source_ref='movement-raw-ref',
            ).exists(),
        )

    def test_cleanup_removes_upload_bank_payload_and_pdf(self) -> None:
        self.assertEqual(self._cleanup(), 1)

        self.upload.refresh_from_db()
        self.assertIsNotNone(self.upload.retention_cleaned_at)
        self.assertEqual(self.upload.file_hash, 'file-hash')
        self.assertEqual(self.upload.expires_at, self.expires_at)
        self.assertFalse(bool(self.upload.pdf_file))
        self.assertFalse(self.storage.exists(self.pdf_name))
        self.assertIsNone(self.upload.statement_closing_balance)
        self.assertIsNone(self.upload.account_balance_after)
        self.assertIsNone(self.upload.balance_discrepancy)
        self.assertEqual(self.upload.error_message, '')
        self.assertEqual(self.upload.celery_task_id, '')

    def test_cleaned_unresolved_upload_is_not_falsely_completed(self) -> None:
        self.assertEqual(self._cleanup(), 1)

        self.upload.refresh_from_db()
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        self.assertEqual(self.upload.awaiting_decision_count, 2)
        self.assertEqual(self.upload.expired_count, 1)
        self.assertEqual(self.upload.linked_count, 1)
        self.assertEqual(self.upload.needs_transfer_count, 0)

    def test_second_cleanup_changes_nothing(self) -> None:
        self.assertEqual(self._cleanup(), 1)

        self.assertEqual(self._cleanup(), 0)

    def test_excluded_and_linked_only_upload_completes(self) -> None:
        excluded_upload = self._other_upload(
            BankStatementUpload.Status.COMPLETED,
        )
        self._other_row(
            excluded_upload,
            1,
            BankStatementRow.Decision.EXCLUDED,
        )
        self._other_row(
            excluded_upload,
            2,
            BankStatementRow.Decision.LINKED,
        )

        container = ApplicationContainer()
        cleaned = container.users.bank_statement_retention_service()
        self.assertEqual(cleaned.cleanup_expired(), 2)

        excluded_upload.refresh_from_db()
        self.assertEqual(
            excluded_upload.status,
            BankStatementUpload.Status.COMPLETED,
        )

    def test_awaiting_markup_upload_stays_awaiting_after_cleanup(self) -> None:
        markup_upload = self._other_upload(
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self._other_row(
            markup_upload,
            1,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

        self.upload.expires_at = timezone.now() + timedelta(days=1)
        self.upload.save(update_fields=['expires_at'])
        container = ApplicationContainer()
        cleaned = container.users.bank_statement_retention_service()
        cleaned.cleanup_expired()

        markup_upload.refresh_from_db()
        self.assertEqual(
            markup_upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        row = markup_upload.statement_rows.get()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertFalse(row_has_bank_data(row))

    def test_raw_source_ref_without_hash_refuses_cleanup(self) -> None:
        raw_upload = self._other_upload(BankStatementUpload.Status.COMPLETED)
        raw_row = self._other_row(
            raw_upload,
            1,
            BankStatementRow.Decision.PENDING,
            source_ref='unconverted-raw',
        )
        raw_row.source_ref_hash = None
        raw_row.save(update_fields=['source_ref_hash'])
        raw_upload.pdf_file.save(
            'raw.pdf',
            SimpleUploadedFile(
                'raw.pdf',
                b'%PDF-1.4 raw',
                content_type='application/pdf',
            ),
        )
        pdf_name = raw_upload.pdf_file.name
        storage = raw_upload.pdf_file.storage
        self.upload.expires_at = timezone.now() + timedelta(days=1)
        self.upload.save(update_fields=['expires_at'])

        container = ApplicationContainer()
        service = container.users.bank_statement_retention_service()
        self.assertEqual(service.cleanup_expired(), 0)

        raw_upload.refresh_from_db()
        raw_row.refresh_from_db()
        self.assertIsNone(raw_upload.retention_cleaned_at)
        self.assertEqual(
            raw_upload.status,
            BankStatementUpload.Status.COMPLETED,
        )
        self.assertIsNone(raw_row.data_cleaned_at)
        self.assertEqual(raw_row.amount, Decimal('25.00'))
        self.assertEqual(raw_row.source_ref, 'unconverted-raw')
        self.assertTrue(bool(raw_upload.pdf_file))
        self.assertTrue(storage.exists(pdf_name))

    def test_stale_cleanup_does_not_delete_renewed_file(self) -> None:
        renew_upload = self._other_upload(BankStatementUpload.Status.COMPLETED)
        self._other_row(renew_upload, 1, BankStatementRow.Decision.PENDING)
        renew_upload.pdf_file.save(
            'old.pdf',
            SimpleUploadedFile(
                'old.pdf',
                b'%PDF-1.4 old',
                content_type='application/pdf',
            ),
        )
        storage = renew_upload.pdf_file.storage
        moment = timezone.now() - timedelta(seconds=1)
        BankStatementUpload.objects.filter(pk=renew_upload.pk).update(
            expires_at=timezone.now() + timedelta(days=1),
        )
        renew_upload.refresh_from_db()
        renew_upload.pdf_file.save(
            'new.pdf',
            SimpleUploadedFile(
                'new.pdf',
                b'%PDF-1.4 new',
                content_type='application/pdf',
            ),
        )
        new_name = renew_upload.pdf_file.name

        container = ApplicationContainer()
        service = container.users.bank_statement_retention_service()
        cleaned = service._cleanup_upload(renew_upload.pk, moment)

        self.assertFalse(cleaned)
        renew_upload.refresh_from_db()
        self.assertIsNone(renew_upload.retention_cleaned_at)
        self.assertEqual(renew_upload.pdf_file.name, new_name)
        self.assertTrue(storage.exists(new_name))

    def test_future_row_on_expired_upload_waits_for_its_deadline(self) -> None:
        self.upload.expires_at = timezone.now() + timedelta(days=30)
        self.upload.save(update_fields=['expires_at'])
        moment = timezone.now()
        upload = self._other_upload(BankStatementUpload.Status.COMPLETED)
        upload.expires_at = moment - timedelta(seconds=1)
        upload.statement_closing_balance = Decimal('500.00')
        upload.balance_discrepancy = Decimal('10.00')
        upload.save(
            update_fields=[
                'expires_at',
                'statement_closing_balance',
                'balance_discrepancy',
            ],
        )
        future = self._other_row(
            upload,
            1,
            BankStatementRow.Decision.PENDING,
        )
        future.data_expires_at = moment + timedelta(days=7)
        future.save(update_fields=['data_expires_at'])
        due = self._other_row(upload, 2, BankStatementRow.Decision.DEFERRED)

        container = ApplicationContainer()
        service = container.users.bank_statement_retention_service()
        self.assertEqual(service.cleanup_expired(moment), 1)

        upload.refresh_from_db()
        future.refresh_from_db()
        due.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        self.assertIsNone(upload.statement_closing_balance)
        self.assertIsNone(upload.balance_discrepancy)
        self.assertEqual(future.amount, Decimal('25.00'))
        self.assertEqual(future.description, 'Секретная строка')
        self.assertIsNone(future.data_cleaned_at)
        self.assertIsNotNone(due.data_cleaned_at)
        marker = upload.retention_cleaned_at

        later = moment + timedelta(days=8)
        self.assertEqual(service.cleanup_expired(later), 1)

        upload.refresh_from_db()
        future.refresh_from_db()
        self.assertEqual(upload.retention_cleaned_at, marker)
        self.assertIsNone(future.amount)
        self.assertEqual(future.description, '')
        self.assertIsNotNone(future.data_cleaned_at)
        self.assertEqual(
            future.decision,
            BankStatementRow.Decision.PENDING,
        )

    def test_restored_row_on_cleaned_upload_is_cleaned_by_row_deadline(
        self,
    ) -> None:
        self.upload.expires_at = timezone.now() + timedelta(days=1)
        self.upload.save(update_fields=['expires_at'])
        moment = timezone.now()
        upload = self._other_upload(BankStatementUpload.Status.COMPLETED)
        upload.retention_cleaned_at = moment - timedelta(days=1)
        upload.save(update_fields=['retention_cleaned_at'])
        row = self._other_row(
            upload,
            1,
            BankStatementRow.Decision.DEFERRED,
        )
        row.data_expires_at = moment - timedelta(seconds=1)
        row.save(update_fields=['data_expires_at'])

        container = ApplicationContainer()
        service = container.users.bank_statement_retention_service()
        self.assertEqual(service.cleanup_expired(moment), 1)

        upload.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(
            upload.retention_cleaned_at,
            moment - timedelta(days=1),
        )
        self.assertFalse(bool(upload.pdf_file))
        self.assertEqual(row.amount, None)
        self.assertEqual(row.description, '')
        self.assertIsNotNone(row.data_cleaned_at)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.DEFERRED,
        )

    def test_legacy_cleaned_row_without_deadline_is_not_due(self) -> None:
        self.upload.expires_at = timezone.now() + timedelta(days=1)
        self.upload.save(update_fields=['expires_at'])
        moment = timezone.now()
        upload = self._other_upload(BankStatementUpload.Status.COMPLETED)
        upload.retention_cleaned_at = moment - timedelta(days=1)
        upload.save(update_fields=['retention_cleaned_at'])
        row = self._other_row(
            upload,
            1,
            BankStatementRow.Decision.PENDING,
        )
        row.data_expires_at = None
        row.save(update_fields=['data_expires_at'])

        container = ApplicationContainer()
        service = container.users.bank_statement_retention_service()
        self.assertEqual(service.cleanup_expired(moment), 0)

        row.refresh_from_db()
        self.assertEqual(row.amount, Decimal('25.00'))
        self.assertIsNone(row.data_cleaned_at)

    def _other_upload(self, status: str) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=status,
            expires_at=timezone.now() - timedelta(seconds=1),
        )

    def _other_row(
        self,
        upload: BankStatementUpload,
        position: int,
        decision: str,
        *,
        source_ref: str | None = None,
        data_expires_at: datetime | None = None,
        data_cleaned_at: datetime | None = None,
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('25.00'),
            description='Секретная строка',
            source_ref=source_ref or f'other-{position}',
            source_ref_hash=f'{"b" * 63}{position}',
            source_row_position=position,
            data_expires_at=data_expires_at,
            data_cleaned_at=data_cleaned_at,
            decision=decision,
        )


class StatementRowAvailabilityTest(TestCase):
    """Bank data availability is decided per row, not only per upload."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Банк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.service = ApplicationContainer().users.statement_row_link_service()
        self.markup = ApplicationContainer().users.statement_markup_service()
        self.reconciliation = (
            ApplicationContainer().users.bank_statement_reconciliation_service()
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )

    def _row(
        self,
        *,
        upload: BankStatementUpload | None = None,
        position: int = 1,
        data_expires_at: datetime | None = None,
        data_cleaned_at: datetime | None = None,
        decision: str = BankStatementRow.Decision.AWAITING_MARKUP,
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=upload or self.upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('100.00'),
            description='ПЯТЁРОЧКА',
            source_ref=f'raw-{position}',
            source_ref_hash=f'{"c" * 63}{position}',
            source_row_position=position,
            data_expires_at=data_expires_at,
            data_cleaned_at=data_cleaned_at,
            decision=decision,
        )

    def _assert_no_money(self) -> None:
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertFalse(Transaction.objects.exists())

    def test_explicit_row_deadline_wins_over_upload_cleanup_marker(
        self,
    ) -> None:
        self.upload.retention_cleaned_at = timezone.now()
        self.upload.save(update_fields=['retention_cleaned_at'])
        row = self._row(data_expires_at=timezone.now() + timedelta(days=7))

        self.assertTrue(row_has_bank_data(row))
        resumed = self.service.defer(row.pk, self.user.pk)

        self.assertEqual(resumed.decision, BankStatementRow.Decision.DEFERRED)
        self._assert_no_money()

    def test_upload_cleanup_marker_blocks_legacy_row(self) -> None:
        self.upload.retention_cleaned_at = timezone.now()
        self.upload.save(update_fields=['retention_cleaned_at'])
        row = self._row()

        self.assertFalse(row_has_bank_data(row))
        with self.assertRaises(ReconciliationExpiredError):
            self.service.defer(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self._assert_no_money()

    def test_explicit_expired_row_deadline_blocks_decision(self) -> None:
        row = self._row(data_expires_at=timezone.now() - timedelta(seconds=1))

        self.assertFalse(row_has_bank_data(row))
        with self.assertRaises(ReconciliationExpiredError):
            self.service.defer(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_row_cleaned_at_blocks_decision_despite_future_deadline(
        self,
    ) -> None:
        row = self._row(
            data_expires_at=timezone.now() + timedelta(days=7),
            data_cleaned_at=timezone.now(),
        )

        self.assertFalse(row_has_bank_data(row))
        with self.assertRaises(ReconciliationExpiredError):
            self.service.defer(row.pk, self.user.pk)

    def test_markup_guard_uses_row_deadline(self) -> None:
        row = self._row(data_expires_at=timezone.now() - timedelta(seconds=1))

        with self.assertRaises(StatementMarkupConflictError):
            self.markup.post(row.pk, self.user.pk, self.category.pk)

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self._assert_no_money()

    def test_pending_summary_skips_cleaned_and_keeps_restored(self) -> None:
        self._row(data_cleaned_at=timezone.now())
        restored_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            expires_at=timezone.now() - timedelta(days=1),
            retention_cleaned_at=timezone.now(),
        )
        self._row(
            upload=restored_upload,
            position=2,
            data_expires_at=timezone.now() + timedelta(days=7),
        )

        count, upload_id = self.markup.pending_summary(self.user.pk)

        self.assertEqual(count, 1)
        self.assertEqual(upload_id, restored_upload.pk)

    def test_upload_history_restore_count_aggregates_problem(self) -> None:
        self.upload.retention_cleaned_at = timezone.now()
        self.upload.save(update_fields=['retention_cleaned_at'])
        self._row(data_cleaned_at=timezone.now(), decision='pending')
        self._row(data_cleaned_at=timezone.now(), position=2)
        self._row(
            data_expires_at=timezone.now() + timedelta(days=7),
            position=3,
            decision=BankStatementRow.Decision.DEFERRED,
        )

        history = self.reconciliation.upload_history(self.user.pk).get(
            pk=self.upload.pk,
        )

        self.assertEqual(history.restore_count, 2)

    def test_upload_page_shows_recovery_problem_without_details(
        self,
    ) -> None:
        self.upload.retention_cleaned_at = timezone.now()
        self.upload.save(update_fields=['retention_cleaned_at'])
        self._row(data_cleaned_at=timezone.now(), decision='pending')
        self._row(data_cleaned_at=timezone.now(), position=2)
        client = Client()
        client.force_login(self.user)

        response = client.get(reverse('finance_account:bank_statement_upload'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Требуется повторная загрузка: 2')
        self.assertNotContains(response, 'ПЯТЁРОЧКА')


BARRIER_TIMEOUT: Final = 10
FUTURE_TIMEOUT: Final = 30
LOCK_TIMEOUT: Final = '5s'
STATEMENT_TIMEOUT: Final = '15s'


class StatementRetentionConcurrencyTest(TransactionTestCase):
    """Cleanup and a decision race on separate connections without dupes."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Банк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.upload.pdf_file.save(
            'race.pdf',
            SimpleUploadedFile(
                'race.pdf',
                b'%PDF-1.4 race',
                content_type='application/pdf',
            ),
        )
        self.pdf_name = self.upload.pdf_file.name
        self.storage = self.upload.pdf_file.storage
        self.row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('100.00'),
            description='ПЯТЁРОЧКА',
            source_ref='raw-1',
            source_ref_hash='d' * 64,
            source_row_position=1,
            decision=BankStatementRow.Decision.PENDING,
        )

    def _service(self) -> BankStatementRetentionService:
        return cast(
            'BankStatementRetentionService',
            ApplicationContainer().users.bank_statement_retention_service(),
        )

    def _run_together(
        self,
        *calls: Callable[[], object],
    ) -> list[Exception]:
        barrier = Barrier(len(calls))
        errors: list[Exception] = []

        def worker(call: Callable[[], object]) -> None:
            barrier.wait(timeout=BARRIER_TIMEOUT)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT set_config('lock_timeout', %s, false)",
                        [LOCK_TIMEOUT],
                    )
                    cursor.execute(
                        "SELECT set_config('statement_timeout', %s, false)",
                        [STATEMENT_TIMEOUT],
                    )
                call()
            except Exception as error:
                errors.append(error)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(worker, call) for call in calls]
            for future in futures:
                future.result(timeout=FUTURE_TIMEOUT)
        return errors

    def test_cleanup_and_decision_leave_one_state_without_money(self) -> None:
        row_id = self.row.pk
        user_id = self.user.pk
        link_service = ApplicationContainer().users.statement_row_link_service()

        errors = self._run_together(
            lambda: self._service().cleanup_expired(),
            lambda: link_service.defer(row_id, user_id),
        )

        unexpected = [
            error
            for error in errors
            if not isinstance(error, ReconciliationExpiredError)
        ]
        self.assertEqual(unexpected, [])
        self.row.refresh_from_db()
        self.upload.refresh_from_db()
        self.assertIn(
            self.row.decision,
            {
                BankStatementRow.Decision.PENDING,
                BankStatementRow.Decision.DEFERRED,
            },
        )
        self.assertLessEqual(self.row.decision_audits.count(), 1)
        self.assertIsNotNone(self.row.data_cleaned_at)
        self.assertIsNotNone(self.upload.retention_cleaned_at)
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        self.assertFalse(self.storage.exists(self.pdf_name))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertFalse(Transaction.objects.exists())

    def _restore_partial_row(self, row_id: int) -> None:
        """Simulate ticket 06 restoring one row and a new PDF generation.

        Contract: a new PDF generation resets the upload cleanup marker and
        sets a new deadline. Unrestored legacy rows that were only considered
        cleaned through the old upload marker are stamped with that marker
        first, so their availability is not extended.
        """
        future = timezone.now() + timedelta(days=7)
        with transaction.atomic():
            Account.objects.select_for_update().get(pk=self.account.pk)
            upload = BankStatementUpload.objects.select_for_update().get(
                pk=self.upload.pk,
            )
            row = BankStatementRow.objects.select_for_update().get(
                pk=row_id,
                upload=upload,
            )
            old_marker = upload.retention_cleaned_at
            if old_marker is not None:
                BankStatementRow.objects.filter(
                    upload=upload,
                    data_expires_at__isnull=True,
                    data_cleaned_at__isnull=True,
                ).exclude(pk=row.pk).update(data_cleaned_at=old_marker)
            row.amount = Decimal('100.00')
            row.description = 'ПЯТЁРОЧКА'
            row.data_expires_at = future
            row.data_cleaned_at = None
            row.save(
                update_fields=[
                    'amount',
                    'description',
                    'data_expires_at',
                    'data_cleaned_at',
                ],
            )
            upload.expires_at = future
            upload.retention_cleaned_at = None
            upload.pdf_file.save(
                'restored.pdf',
                SimpleUploadedFile(
                    'restored.pdf',
                    b'%PDF-1.4 restored',
                    content_type='application/pdf',
                ),
            )

    def test_cleanup_and_partial_restore_keep_restored_generation(self) -> None:
        row_id = self.row.pk
        moment = timezone.now()
        service = self._service()

        errors = self._run_together(
            lambda: service.cleanup_expired(moment),
            lambda: self._restore_partial_row(row_id),
        )

        self.assertEqual(errors, [])
        self.row.refresh_from_db()
        self.upload.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertEqual(self.row.amount, Decimal('100.00'))
        self.assertEqual(self.row.description, 'ПЯТЁРОЧКА')
        self.assertIsNone(self.row.data_cleaned_at)
        if self.row.data_expires_at is None:
            self.fail('data_expires_at is missing')
        self.assertGreater(self.row.data_expires_at, moment)
        self.assertTrue(row_has_bank_data(self.row))
        self.assertIsNone(self.upload.retention_cleaned_at)
        self.assertGreater(self.upload.expires_at, moment)
        self.assertTrue(
            self.upload.pdf_file.storage.exists(self.upload.pdf_file.name),
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertFalse(Transaction.objects.exists())

    def test_renewed_generation_is_cleaned_after_its_new_deadline(self) -> None:
        old_marker = timezone.now() - timedelta(days=1)
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            retention_cleaned_at=old_marker,
        )
        legacy = BankStatementRow.objects.create(
            upload=self.upload,
            source_row_position=2,
            amount=None,
            description='',
            source_ref_hash='e' * 64,
            decision=BankStatementRow.Decision.PENDING,
        )

        self._restore_partial_row(self.row.pk)

        self.row.refresh_from_db()
        legacy.refresh_from_db()
        self.upload.refresh_from_db()
        self.assertIsNone(self.upload.retention_cleaned_at)
        self.assertEqual(legacy.data_cleaned_at, old_marker)
        new_deadline = self.upload.expires_at
        restored_pdf = self.upload.pdf_file.name
        storage = self.upload.pdf_file.storage

        service = self._service()
        self.assertEqual(
            service.cleanup_expired(new_deadline + timedelta(seconds=1)),
            1,
        )

        self.upload.refresh_from_db()
        self.row.refresh_from_db()
        legacy.refresh_from_db()
        self.assertFalse(storage.exists(restored_pdf))
        self.assertFalse(bool(self.upload.pdf_file))
        self.assertIsNone(self.row.amount)
        self.assertEqual(self.row.description, '')
        self.assertIsNotNone(self.row.data_cleaned_at)
        self.assertEqual(legacy.data_cleaned_at, old_marker)
        self.assertEqual(legacy.description, '')
        self.assertIsNotNone(self.upload.retention_cleaned_at)

    def test_two_cleanups_clean_once(self) -> None:
        results: list[int] = []

        def cleanup() -> None:
            results.append(self._service().cleanup_expired())

        errors = self._run_together(cleanup, cleanup)

        self.assertEqual(errors, [])
        self.assertEqual(sum(results), 1)
        self.upload.refresh_from_db()
        self.row.refresh_from_db()
        self.assertIsNotNone(self.upload.retention_cleaned_at)
        self.assertIsNotNone(self.row.data_cleaned_at)
        self.assertEqual(self.row.decision_audits.count(), 0)
        self.assertFalse(self.storage.exists(self.pdf_name))


class StatementRetentionCommitSafetyTest(TestCase):
    """The PDF is deleted only after the cleanup transaction committed."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Банк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            expires_at=timezone.now() - timedelta(seconds=1),
            file_hash='commit-safety-hash',
        )
        self.upload.pdf_file.save(
            'commit-safety.pdf',
            SimpleUploadedFile(
                'commit-safety.pdf',
                b'%PDF-1.4 commit safety',
                content_type='application/pdf',
            ),
        )
        self.pdf_name = self.upload.pdf_file.name
        self.storage = self.upload.pdf_file.storage
        self.row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('10.00'),
            description='Секретная строка',
            source_ref='raw-commit-ref',
            source_ref_hash='c' * 64,
            source_row_position=1,
            decision=BankStatementRow.Decision.PENDING,
        )

    def _service(self) -> BankStatementRetentionService:
        return cast(
            'BankStatementRetentionService',
            ApplicationContainer().users.bank_statement_retention_service(),
        )

    def test_late_scrub_failure_keeps_pdf_and_rolls_back(self) -> None:
        with (
            patch(
                'hasta_la_vista_money.users.services.'
                'bank_statement_retention.'
                'scrub_transaction_source_ref_audit',
                side_effect=RuntimeError('scrub failed'),
            ),
            self.assertRaises(RuntimeError),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self._service().cleanup_expired()

        self.upload.refresh_from_db()
        self.row.refresh_from_db()
        self.assertIsNone(self.upload.retention_cleaned_at)
        self.assertIsNone(self.row.data_cleaned_at)
        self.assertTrue(bool(self.upload.pdf_file))
        self.assertTrue(self.storage.exists(self.pdf_name))

    def test_late_database_failure_keeps_pdf_and_rolls_back(self) -> None:
        service = self._service()
        with (
            patch.object(
                service.reconciliation_service,
                'refresh_outcome_counts',
                side_effect=RuntimeError('database failed'),
            ),
            self.assertRaises(RuntimeError),
            self.captureOnCommitCallbacks(execute=True),
        ):
            service.cleanup_expired()

        self.upload.refresh_from_db()
        self.assertIsNone(self.upload.retention_cleaned_at)
        self.assertTrue(bool(self.upload.pdf_file))
        self.assertTrue(self.storage.exists(self.pdf_name))

    def test_pdf_is_deleted_only_after_commit(self) -> None:
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.assertEqual(self._service().cleanup_expired(), 1)

        self.upload.refresh_from_db()
        self.assertIsNotNone(self.upload.retention_cleaned_at)
        self.assertTrue(bool(self.upload.pdf_file))
        self.assertTrue(self.storage.exists(self.pdf_name))

        for callback in callbacks:
            callback()

        self.upload.refresh_from_db()
        self.assertFalse(bool(self.upload.pdf_file))
        self.assertFalse(self.storage.exists(self.pdf_name))
        self.assertIsNotNone(self.upload.retention_cleaned_at)

    def test_delete_failure_is_retryable(self) -> None:
        with (
            patch.object(
                self.storage,
                'delete',
                side_effect=OSError('storage unavailable'),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.assertEqual(self._service().cleanup_expired(), 1)

        self.upload.refresh_from_db()
        self.assertIsNotNone(self.upload.retention_cleaned_at)
        self.assertEqual(self.upload.pdf_file.name, self.pdf_name)
        self.assertTrue(self.storage.exists(self.pdf_name))

        with self.captureOnCommitCallbacks(execute=True):
            self._service().cleanup_expired()

        self.upload.refresh_from_db()
        self.assertFalse(bool(self.upload.pdf_file))
        self.assertFalse(self.storage.exists(self.pdf_name))

    def test_replaced_generation_is_not_deleted(self) -> None:
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self._service().cleanup_expired()

        self.assertTrue(self.storage.exists(self.pdf_name))

        self.upload.pdf_file.save(
            'new-generation.pdf',
            SimpleUploadedFile(
                'new-generation.pdf',
                b'%PDF-1.4 new generation',
                content_type='application/pdf',
            ),
        )
        new_name = self.upload.pdf_file.name
        self.upload.expires_at = timezone.now() + timedelta(days=7)
        self.upload.retention_cleaned_at = None
        self.upload.save(
            update_fields=['expires_at', 'retention_cleaned_at'],
        )

        for callback in callbacks:
            callback()

        self.upload.refresh_from_db()
        self.assertEqual(self.upload.pdf_file.name, new_name)
        self.assertTrue(self.storage.exists(new_name))
        self.assertIsNone(self.upload.retention_cleaned_at)
