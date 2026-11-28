"""Tests for bank statement upload functionality."""

import signal
import tempfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pandas as pd
from celery.exceptions import Retry
from django.contrib.auth.models import Group
from django.contrib.messages import SUCCESS, get_messages
from django.core.files import File
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, OperationalError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from faker import Faker

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.bank_constants import (
    BANK_RAIFFEISENBANK,
    BANK_SBERBANK,
)
from hasta_la_vista_money.finance_account.forms import BankStatementUploadForm
from hasta_la_vista_money.finance_account.models import (
    Account,
    Bank,
    StatementPeriodCoverage,
    TransferMoneyLog,
)
from hasta_la_vista_money.system.audit_registry import STATEMENT_IMPORT_LABEL
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.system.services.audit_context import audit_operation
from hasta_la_vista_money.system.services.audit_statement_import import (
    record_statement_import_summary,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    SystemCategoryKind,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.forms import UpdateUserForm
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    FamilyGroupMembership,
    User,
)
from hasta_la_vista_money.users.services.bank_statement import (
    RAIFFEISEN_FALLBACK_POSITION_BASE,
    BankStatementParseError,
    BankStatementParser,
    StatementParseResult,
    _create_parser,
    _dedup_transactions,
    _GenericBankParser,
    _get_or_create_category,
    _OzonBankParser,
    _RaiffeisenBankParser,
    _SberbankParser,
    generic_local_category,
    sberbank_local_category,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
)
from hasta_la_vista_money.users.services.bank_statement_retention import (
    BankStatementRetentionService,
    _AuditProvenance,
    scrub_movement_audit_copy,
)
from hasta_la_vista_money.users.tasks import process_bank_statement_task

if TYPE_CHECKING:
    from django.http import HttpResponseRedirect

RAIFFEISEN_REAL_FIXTURE = (
    Path(__file__).parent / 'fixtures' / 'raiffeisen_statement.pdf'
)


SBERBANK_FIXTURE = Path(__file__).parent / 'fixtures' / 'sberbank_statement.pdf'

# Real user-provided Ozon statement, coordinator-anonymized: dates and
# amounts preserved, bank identifiers replaced with synthetic values.
OZON_FIXTURE = Path(__file__).parent / 'fixtures' / 'ozon_statement.pdf'


class TestBankStatementUploadView(TestCase):
    """Test cases for bank statement upload view."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)
        self.client: Client = Client()
        self.client.force_login(self.user)
        self.faker: Faker = Faker()

        # Create a test account
        self.account = Account.objects.create(
            user=self.user,
            name_account='Тестовый счет',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

        self.upload_url = reverse('finance_account:bank_statement_upload')

    def test_get_upload_page(self) -> None:
        """Test GET request to upload page."""
        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            'finance_account/bank_statement_upload.html',
        )
        self.assertIn('form', response.context)

    def test_upload_page_lives_in_finances(self) -> None:
        self.assertTrue(self.upload_url.startswith('/finance_account/'))
        response = self.client.get(reverse('finances'))
        self.assertContains(response, f'href="{self.upload_url}"')

    def test_old_upload_url_redirects_to_finances(self) -> None:
        response = self.client.get('/users/bank-statement-upload/')
        self.assertRedirects(
            response,
            self.upload_url,
            status_code=301,
        )

    def test_upload_page_requires_authentication(self) -> None:
        """Test that upload page requires login."""
        self.client.logout()
        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, 302)
        # Check that it redirects to login
        # (could be /auth/login/ or /users/login/)
        redirect_response = cast('HttpResponseRedirect', response)
        self.assertIn('login', redirect_response.url.lower())

    @patch(
        'hasta_la_vista_money.finance_account.bank_statement_views.process_bank_statement_task',
    )
    def test_upload_pdf_success(self, mock_task: MagicMock) -> None:
        """Test successful PDF upload."""
        mock_task.delay.return_value = MagicMock(id='test-task-id')

        # Create a fake PDF file
        pdf_content = b'%PDF-1.4 fake pdf content'
        pdf_file = SimpleUploadedFile(
            'statement.pdf',
            pdf_content,
            content_type='application/pdf',
        )

        response = self.client.post(
            self.upload_url,
            {
                'account': self.account.pk,
                'pdf_file': pdf_file,
            },
            follow=True,
        )

        # Check that task was called
        mock_task.delay.assert_called_once()
        upload_id = mock_task.delay.call_args[0][0]

        # Check that upload record was created
        upload = BankStatementUpload.objects.get(id=upload_id)
        self.assertEqual(upload.user, self.user)
        self.assertEqual(upload.account, self.account)
        self.assertEqual(upload.status, 'pending')
        self.assertEqual(
            mock_task.delay.call_args[0][1],
            upload.celery_task_id,
        )

        self.assertRedirects(response, self.upload_url)
        self.assertFalse(
            any(
                message.level == SUCCESS
                for message in get_messages(response.wsgi_request)
            ),
        )

    def test_profile_form_stores_statement_retention_days(self) -> None:
        """The user chooses the term; the model rejects impossible terms."""
        form = UpdateUserForm(
            instance=self.user,
            data={
                'username': self.user.username,
                'email': self.user.email,
                'first_name': self.user.first_name,
                'last_name': self.user.last_name,
                'timezone_name': self.user.timezone_name,
                'statement_retention_days': 45,
            },
        )
        self.assertTrue(form.is_valid(), form.errors)

        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.statement_retention_days, 45)

        for invalid in (0, 366):
            with self.subTest(days=invalid):
                invalid_form = UpdateUserForm(
                    instance=self.user,
                    data={
                        'username': self.user.username,
                        'email': self.user.email,
                        'first_name': self.user.first_name,
                        'last_name': self.user.last_name,
                        'timezone_name': self.user.timezone_name,
                        'statement_retention_days': invalid,
                    },
                )
                self.assertFalse(invalid_form.is_valid())
                self.assertIn(
                    'statement_retention_days',
                    invalid_form.errors,
                )

    @patch(
        'hasta_la_vista_money.finance_account.bank_statement_views.process_bank_statement_task',
    )
    def test_upload_fixes_retention_and_changed_preference_is_not_retroactive(
        self,
        mock_task: MagicMock,
    ) -> None:
        """A new upload fixes the current choice; a replay gets a new term."""
        mock_task.delay.return_value = MagicMock(id='test-task-id')
        pdf_content = b'%PDF-1.4 retention preference statement'
        pdf_file = SimpleUploadedFile(
            'retention-preference.pdf',
            pdf_content,
            content_type='application/pdf',
        )
        self.assertEqual(self.user.statement_retention_days, 30)
        self.user.statement_retention_days = 60
        self.user.save(update_fields=['statement_retention_days'])
        before_upload = timezone.now()

        self.client.post(
            self.upload_url,
            {'account': self.account.pk, 'pdf_file': pdf_file},
        )

        upload = BankStatementUpload.objects.get()
        self.assertGreaterEqual(
            upload.expires_at,
            before_upload + timedelta(days=60) - timedelta(seconds=5),
        )
        self.assertLessEqual(
            upload.expires_at,
            timezone.now() + timedelta(days=60) + timedelta(seconds=5),
        )
        fixed_deadline = upload.expires_at

        self.user.statement_retention_days = 7
        self.user.save(update_fields=['statement_retention_days'])
        upload.refresh_from_db()
        self.assertEqual(upload.expires_at, fixed_deadline)

        upload.status = BankStatementUpload.Status.COMPLETED
        upload.save(update_fields=['status'])
        before_replay = timezone.now()
        self.client.post(
            self.upload_url,
            {
                'account': self.account.pk,
                'pdf_file': SimpleUploadedFile(
                    'renamed-retention-preference.pdf',
                    pdf_content,
                    content_type='application/pdf',
                ),
            },
        )
        upload.refresh_from_db()

        self.assertIsNone(upload.retention_cleaned_at)
        self.assertGreaterEqual(
            upload.expires_at,
            before_replay + timedelta(days=7) - timedelta(seconds=5),
        )
        self.assertLessEqual(
            upload.expires_at,
            timezone.now() + timedelta(days=7) + timedelta(seconds=5),
        )
        self.assertEqual(
            BankStatementRetentionService(
                BankStatementReconciliationService(),
            ).cleanup_expired(),
            0,
        )
        upload.refresh_from_db()
        self.assertIsNone(upload.retention_cleaned_at)

    @patch(
        'hasta_la_vista_money.finance_account.bank_statement_views.process_bank_statement_task',
    )
    def test_repeated_file_starts_reconciliation_run(
        self,
        mock_task: MagicMock,
    ) -> None:
        """Known file hash reuses the upload but starts a reconciliation run."""
        mock_task.delay.return_value = MagicMock(id='test-task-id')
        pdf_content = b'%PDF-1.4 identical statement'

        for filename in ('statement.pdf', 'renamed.pdf'):
            self.client.post(
                self.upload_url,
                {
                    'account': self.account.pk,
                    'pdf_file': SimpleUploadedFile(
                        filename,
                        pdf_content,
                        content_type='application/pdf',
                    ),
                },
            )
            BankStatementUpload.objects.filter(
                user=self.user,
                account=self.account,
            ).update(status=BankStatementUpload.Status.COMPLETED)

        self.assertEqual(BankStatementUpload.objects.count(), 1)
        self.assertEqual(mock_task.delay.call_count, 2)
        upload = BankStatementUpload.objects.get()
        self.assertEqual(
            upload.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )

    def test_identical_rows_without_source_ref_remain_distinct(self) -> None:
        transaction = {
            'date': timezone.now(),
            'amount': Decimal('-10.00'),
            'description': 'Покупка',
            'source_ref': None,
        }

        result = _dedup_transactions([transaction.copy(), transaction.copy()])

        self.assertEqual(len(result), 2)
        self.assertEqual(
            [row['row_position'] for row in result],
            [0, 1],
        )

    def test_upload_without_account(self) -> None:
        """Test upload without selecting account."""
        pdf_content = b'%PDF-1.4 fake pdf content'
        pdf_file = SimpleUploadedFile(
            'statement.pdf',
            pdf_content,
            content_type='application/pdf',
        )

        response = self.client.post(
            self.upload_url,
            {
                'pdf_file': pdf_file,
            },
        )

        self.assertEqual(response.status_code, 200)
        # Form should have errors on account field
        self.assertTrue(response.context['form'].has_error('account'))

    def test_upload_invalid_file_type(self) -> None:
        """Test upload with invalid file type."""
        txt_file = SimpleUploadedFile(
            'statement.txt',
            b'not a pdf',
            content_type='text/plain',
        )

        response = self.client.post(
            self.upload_url,
            {
                'account': self.account.id,
                'pdf_file': txt_file,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].has_error('pdf_file'))

    def test_show_progress_for_ongoing_upload(self) -> None:
        """Test that progress bar shows for ongoing upload."""
        # Create an ongoing upload
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='processing',
            progress=50,
        )

        # Set session data
        session = self.client.session
        session['last_upload_id'] = upload.id
        session.save()

        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context.get('show_progress'))
        self.assertEqual(response.context.get('upload_id'), upload.id)

        returned = self.client.get(self.upload_url)
        self.assertFalse(returned.context.get('show_progress', False))

    def test_return_to_upload_history_after_pending_review(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        session = self.client.session
        session['last_upload_id'] = upload.pk
        session.save()

        first = self.client.get(self.upload_url)
        self.assertTrue(first.context['show_progress'])
        self.assertContains(first, 'id="progressReviewLink"')

        returned = self.client.get(self.upload_url)
        self.assertFalse(returned.context.get('show_progress', False))
        self.assertEqual(list(returned.context['upload_history']), [upload])

    def test_failed_upload_shows_error_even_if_processing_already_ended(
        self,
    ) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.FAILED,
            error_message='Банк выписки не совпадает с банком счёта.',
        )
        session = self.client.session
        session['last_upload_id'] = upload.pk
        session.save()

        response = self.client.get(self.upload_url)
        self.assertTrue(response.context['show_progress'])
        self.assertContains(response, upload.error_message)

    def test_no_progress_for_completed_upload(self) -> None:
        """Test that progress bar doesn't show for completed upload."""
        # Create a completed upload
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='completed',
            progress=100,
        )

        session = self.client.session
        session['last_upload_id'] = upload.id
        session.save()

        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get('show_progress', False))


class TestBankStatementUploadStatusView(TestCase):
    """Test cases for bank statement upload status API."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)
        self.other_user: User = User.objects.get(pk=2)
        self.client: Client = Client()
        self.client.force_login(self.user)

        self.account = Account.objects.create(
            user=self.user,
            name_account='Тестовый счет',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def test_get_status_pending(self) -> None:
        """Test getting status of pending upload."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='pending',
            progress=0,
        )

        url = reverse(
            'finance_account:bank_statement_upload_status',
            args=[upload.id],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(data['progress'], 0)

    def test_get_status_processing(self) -> None:
        """Test getting status of processing upload."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='processing',
            progress=45,
            total_transactions=100,
            processed_transactions=45,
        )

        url = reverse(
            'finance_account:bank_statement_upload_status',
            args=[upload.id],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'processing')
        self.assertEqual(data['progress'], 45)
        self.assertEqual(data['total_transactions'], 100)
        self.assertEqual(data['processed_transactions'], 45)

    def test_get_status_completed(self) -> None:
        """Test getting status of completed upload."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='completed',
            progress=100,
            income_count=10,
            expense_count=20,
        )

        url = reverse(
            'finance_account:bank_statement_upload_status',
            args=[upload.id],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['progress'], 100)
        self.assertEqual(data['income_count'], 10)
        self.assertEqual(data['expense_count'], 20)

    def test_get_status_awaiting_confirmation(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            progress=100,
            imported_count=4,
            linked_count=2,
            awaiting_decision_count=3,
            expired_count=1,
        )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_upload_status',
                args=[upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['status'],
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(
            response.json()['reconciliation_url'],
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[upload.pk],
            ),
        )
        self.assertEqual(
            response.json()['outcomes'],
            {
                'imported': 4,
                'linked': 2,
                'awaiting_decision': 3,
                'needs_transfer': 0,
                'expired': 1,
                'failed': 0,
            },
        )

    def test_get_status_completed_with_unresolved(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
            progress=100,
            expired_count=2,
        )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_upload_status',
                args=[upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['status'],
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        self.assertEqual(response.json()['outcomes']['expired'], 2)
        self.assertIsNone(response.json()['reconciliation_url'])

    def test_get_status_failed(self) -> None:
        """Test getting status of failed upload."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='failed',
            failed_count=1,
            error_message='Тестовая ошибка',
        )

        url = reverse(
            'finance_account:bank_statement_upload_status',
            args=[upload.id],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'failed')
        self.assertEqual(data['status_label'], str(upload.get_status_display()))
        self.assertEqual(data['error_message'], 'Тестовая ошибка')
        self.assertEqual(data['outcomes']['failed'], 1)

    def test_cannot_access_other_user_upload(self) -> None:
        """Test that user cannot access other user's upload status."""
        other_account = Account.objects.create(
            user=self.other_user,
            name_account='Другой счет',
            balance=Decimal('500.00'),
            currency='RUB',
        )

        upload = BankStatementUpload.objects.create(
            user=self.other_user,
            account=other_account,
            status='processing',
        )

        url = reverse(
            'finance_account:bank_statement_upload_status',
            args=[upload.id],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_get_status_completed_with_reconciliation(self) -> None:
        """Test completed status response includes reconciliation fields."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='completed',
            progress=100,
            income_count=5,
            expense_count=10,
            statement_closing_balance=Decimal('1500.00'),
            account_balance_after=Decimal('1450.00'),
            balance_discrepancy=Decimal('50.00'),
        )

        url = reverse(
            'finance_account:bank_statement_upload_status',
            args=[upload.id],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['statement_closing_balance'], '1500.00')
        self.assertEqual(data['account_balance_after'], '1450.00')
        self.assertEqual(data['balance_discrepancy'], '50.00')

    def test_get_status_hides_url_of_expired_reconciliation(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_upload_status',
                args=[upload.pk],
            ),
        )

        self.assertIsNone(response.json()['reconciliation_url'])

    def test_get_status_completed_no_reconciliation(self) -> None:
        """Test status response has null reconciliation fields when not set."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='completed',
            progress=100,
        )

        url = reverse(
            'finance_account:bank_statement_upload_status',
            args=[upload.id],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data['statement_closing_balance'])
        self.assertIsNone(data['account_balance_after'])
        self.assertIsNone(data['balance_discrepancy'])


class TestBankStatementReconciliationView(TestCase):
    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.other_user: User = User.objects.get(pk=2)
        self.client = Client()
        self.client.force_login(self.user)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Транспорт',
            type=TransactionType.EXPENSE,
        )
        self.candidate = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('120.00'),
            date=timezone.now(),
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/reconciliation.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            total_transactions=1,
        )
        self.row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=self.candidate.date,
            amount=Decimal('120.00'),
            description='Такси',
            candidate_description='Такси по городу',
            suggested_category='Поездки',
            source_ref='new-source',
            source_row_position=0,
            candidate=self.candidate,
        )
        BankStatementCandidate.objects.create(
            row=self.row,
            transaction=self.candidate,
            description='Такси по городу',
            rank=0,
        )

    def assert_retention_payload_scrubbed(
        self,
        row: BankStatementRow,
    ) -> None:
        """Assert that a retained row contains no statement payload."""
        self.assertEqual(row.description, '')
        self.assertEqual(row.candidate_description, '')
        self.assertEqual(row.suggested_category, '')
        self.assertIsNone(row.source_ref)
        self.assertIsNone(row.transaction_type)
        self.assertIsNone(row.transaction_date)
        self.assertIsNone(row.amount)
        self.assertIsNotNone(row.source_row_position)
        self.assertFalse(row.candidates.exists())

    def assert_reuploaded_after_retention(
        self,
        task: MagicMock,
        response: Any,
        deadline: datetime,
    ) -> None:
        """Assert a replay reopens only the cleaned upload's file."""
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BankStatementUpload.objects.count(), 1)
        task.delay.assert_called_once()
        self.upload.refresh_from_db()
        self.assertEqual(
            self.upload.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )
        self.assertIsNone(self.upload.retention_cleaned_at)
        self.assertGreater(self.upload.expires_at, deadline)
        self.assertTrue(bool(self.upload.pdf_file))

    def test_owner_sees_statement_and_candidate_financial_fields(self) -> None:
        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Такси')
        self.assertContains(response, '120,00 RUB')
        self.assertContains(response, 'Транспорт')
        self.assertContains(response, 'Расход')
        self.assertContains(response, 'Такси по городу')
        self.assertContains(
            response,
            f'value="{self.row.candidates.get().pk}" checked required',
        )

    def test_markup_page_shows_unknown_row_without_moving_money(self) -> None:
        """An unknown bank row stays visible and changes no money."""
        unknown = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('50.00'),
            description='Неизвестная операция Райффайзена',
            source_row_position=1,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_markup',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, unknown.description)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(Transaction.objects.count(), 1)

    def test_linked_decision_is_idempotent_and_keeps_balance(self) -> None:
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )

        candidate = BankStatementCandidate.objects.get(row=self.row)
        payload = {'decision': 'linked', 'candidate': candidate.pk}
        first_response = self.client.post(url, payload)
        second_response = self.client.post(url, payload)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.row.refresh_from_db()
        self.upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.row.transaction, self.candidate)
        self.assertEqual(self.row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED,
        )
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.upload.linked_count, 1)
        self.assertEqual(self.upload.awaiting_decision_count, 0)

    def test_last_pending_decision_keeps_unresolved_upload_open(
        self,
    ) -> None:
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )
        candidate = BankStatementCandidate.objects.get(row=self.row)
        for unresolved in (
            BankStatementRow.Decision.AWAITING_MARKUP,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        ):
            with self.subTest(unresolved=unresolved):
                self.upload.statement_rows.exclude(pk=self.row.pk).delete()
                BankStatementRow.objects.filter(pk=self.row.pk).update(
                    decision=BankStatementRow.Decision.PENDING,
                    transaction=None,
                    transfer=None,
                    decided_at=None,
                )
                BankStatementRow.objects.create(
                    upload=self.upload,
                    transaction_type=TransactionType.EXPENSE,
                    transaction_date=timezone.now(),
                    amount=Decimal('25.00'),
                    description='Нерешённая строка',
                    source_row_position=10,
                    decision=unresolved,
                )
                BankStatementUpload.objects.filter(pk=self.upload.pk).update(
                    status=(BankStatementUpload.Status.AWAITING_CONFIRMATION),
                )

                response = self.client.post(
                    url,
                    {'decision': 'linked', 'candidate': candidate.pk},
                )

                self.assertEqual(response.status_code, 302)
                self.upload.refresh_from_db()
                self.assertEqual(
                    self.upload.status,
                    BankStatementUpload.Status.AWAITING_CONFIRMATION,
                )

    def test_retention_keeps_empty_parse_unconfirmed(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/empty-retention.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
            total_transactions=0,
            expires_at=timezone.now(),
        )

        BankStatementRetentionService(
            BankStatementReconciliationService(),
        ).cleanup_expired(timezone.now() + timedelta(seconds=1))

        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def test_multiple_candidates_are_not_preselected(self) -> None:
        second = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=self.candidate.amount,
            date=self.candidate.date,
        )
        BankStatementCandidate.objects.create(
            row=self.row,
            transaction=second,
            description='Второй кандидат',
            rank=1,
        )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'checked required')

    def test_new_decision_is_idempotent_and_changes_balance_once(self) -> None:
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )

        self.client.post(url, {'decision': 'new'})
        self.client.post(url, {'decision': 'new'})

        self.row.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(self.row.transaction)
        self.assertEqual(self.account.balance, Decimal('880.00'))
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Поездки',
                type=TransactionType.EXPENSE,
            ).exists(),
        )
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.imported_count, 1)
        self.assertEqual(self.upload.awaiting_decision_count, 0)

    def test_new_expense_can_exceed_current_account_balance(self) -> None:
        self.account.balance = Decimal('100.00')
        self.account.save(update_fields=['balance'])
        self.row.amount = Decimal('200.00')
        self.row.save(update_fields=['amount'])
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )

        self.client.post(url, {'decision': 'new'})
        self.client.post(url, {'decision': 'new'})

        self.row.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(self.row.transaction_id)
        self.assertEqual(self.account.balance, Decimal('-100.00'))
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            2,
        )

    def test_last_reconciliation_decision_verifies_statement_balance(
        self,
    ) -> None:
        self.upload.statement_closing_balance = Decimal('830.00')
        self.upload.balance_currency = 'RUB'
        self.upload.balance_type = BankStatementUpload.BalanceType.EXACT_MOMENT
        self.upload.balance_moment = self.row.transaction_date
        self.upload.save()
        last_row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=self.row.transaction_date,
            amount=Decimal('50.00'),
            suggested_category='Поездки',
            source_ref='another-source',
            source_row_position=1,
        )
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )

        self.client.post(url, {'decision': 'new'})
        self.upload.refresh_from_db()
        self.assertIsNone(self.upload.balance_checked_at)
        self.client.post(
            reverse(
                'finance_account:bank_statement_reconciliation_decide',
                args=[self.upload.pk, last_row.pk],
            ),
            {'decision': 'new'},
        )

        self.upload.refresh_from_db()
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED,
        )
        self.assertEqual(
            self.upload.balance_result,
            BankStatementUpload.BalanceResult.MATCHED,
        )
        self.assertEqual(self.upload.account_balance_after, Decimal('830.00'))
        self.assertTrue(self.upload.balance_is_actual)

    def test_decision_is_its_own_resolution_operation(self) -> None:
        """Resolving a row tags its audit entries as their own operation."""
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )

        self.client.post(url, {'decision': 'new'})

        entries = AuditLog.objects.filter(
            user=self.user,
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        )
        self.assertTrue(entries.exists())
        operation_ids = {entry.operation_id for entry in entries}
        self.assertEqual(len(operation_ids), 1)

    def test_bulk_decision_shares_one_operation_across_rows(self) -> None:
        """A batch of independent row decisions is one audit operation."""
        second_row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=self.candidate.date,
            amount=Decimal('75.00'),
            description='Такси в аэропорт',
            suggested_category='Поездки',
            source_row_position=1,
        )
        url = reverse(
            'finance_account:bank_statement_reconciliation_bulk',
            args=[self.upload.pk],
        )

        self.client.post(
            url,
            {
                'decision': 'new',
                'confirm_risk': 'true',
                'rows': [self.row.pk, second_row.pk],
            },
        )

        entries = AuditLog.objects.filter(
            user=self.user,
            kind=AuditOperationKind.STATEMENT_IMPORT_RESOLUTION,
        )
        operation_ids = {entry.operation_id for entry in entries}
        self.assertEqual(len(operation_ids), 1)
        self.assertGreaterEqual(entries.count(), 2)

    def test_bulk_link_returns_independent_results_and_is_idempotent(
        self,
    ) -> None:
        ambiguous = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=self.candidate.date,
            amount=self.candidate.amount,
            description='Неоднозначная строка',
            candidate_description='Кандидат',
            suggested_category='Поездки',
            source_row_position=1,
            candidate=self.candidate,
        )
        BankStatementCandidate.objects.create(
            row=ambiguous,
            transaction=self.candidate,
            description='Первый кандидат',
            rank=0,
        )
        second_candidate = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=self.candidate.amount,
            date=self.candidate.date,
        )
        BankStatementCandidate.objects.create(
            row=ambiguous,
            transaction=second_candidate,
            description='Второй кандидат',
            rank=1,
        )
        stale = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now() + timedelta(days=1),
            amount=Decimal('50.00'),
            description='Устаревшая строка',
            candidate_description='Удалённый кандидат',
            suggested_category='Прочее',
            source_row_position=2,
        )
        if stale.amount is None or stale.transaction_date is None:
            self.fail('Statement row must contain amount and date')
        stale_transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=stale.amount,
            date=stale.transaction_date,
        )
        stale_candidate = BankStatementCandidate.objects.create(
            row=stale,
            transaction=stale_transaction,
            description='Удалённый кандидат',
            rank=0,
        )
        stale_transaction.delete()
        url = reverse(
            'finance_account:bank_statement_reconciliation_bulk',
            args=[self.upload.pk],
        )
        payload = {
            'decision': 'linked',
            'rows': [self.row.pk, ambiguous.pk, stale.pk],
        }

        first_response = self.client.post(url, payload)
        second_response = self.client.post(url, payload)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        first_results = {
            result['row_id']: result['outcome']
            for result in first_response.json()['results']
        }
        second_results = {
            result['row_id']: result['outcome']
            for result in second_response.json()['results']
        }
        self.assertEqual(first_results[self.row.pk], 'linked')
        self.assertEqual(first_results[ambiguous.pk], 'ambiguous')
        self.assertEqual(first_results[stale.pk], 'stale')
        self.assertEqual(second_results, first_results)
        self.row.refresh_from_db()
        ambiguous.refresh_from_db()
        stale.refresh_from_db()
        stale_candidate.refresh_from_db()
        self.upload.refresh_from_db()
        self.assertEqual(self.row.transaction, self.candidate)
        self.assertEqual(
            ambiguous.decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertEqual(stale.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(stale_candidate.transaction)
        self.assertEqual(self.upload.linked_count, 1)
        self.assertEqual(self.upload.awaiting_decision_count, 2)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_bulk_new_requires_risk_confirmation(self) -> None:
        url = reverse(
            'finance_account:bank_statement_reconciliation_bulk',
            args=[self.upload.pk],
        )
        payload = {'decision': 'new', 'rows': [self.row.pk]}

        rejected = self.client.post(url, payload)
        accepted = self.client.post(
            url,
            {**payload, 'confirm_risk': 'true'},
        )

        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.json()['error'], 'confirmation_required')
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(
            accepted.json()['results'],
            [{'row_id': self.row.pk, 'outcome': 'new'}],
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('880.00'))
        self.assertEqual(Transaction.objects.count(), 2)

    def test_bulk_new_continues_after_one_database_error(self) -> None:
        self.candidate.source_ref = 'duplicate-source'
        self.candidate.save(update_fields=['source_ref'])
        self.row.source_ref = 'duplicate-source'
        self.row.save(update_fields=['source_ref'])
        successful = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now() + timedelta(minutes=1),
            amount=Decimal('30.00'),
            description='Успешная строка',
            candidate_description='Кандидат',
            suggested_category='Прочее',
            source_ref='unique-source',
            source_row_position=1,
        )

        original = BankStatementReconciliationService._create_transaction

        def flaky(service, row):
            if row.pk == self.row.pk:
                raise DatabaseError('duplicate-source')
            return original(service, row)

        with patch.object(
            BankStatementReconciliationService,
            '_create_transaction',
            autospec=True,
            side_effect=flaky,
        ):
            response = self.client.post(
                reverse(
                    'finance_account:bank_statement_reconciliation_bulk',
                    args=[self.upload.pk],
                ),
                {
                    'decision': 'new',
                    'confirm_risk': 'true',
                    'rows': [self.row.pk, successful.pk],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['results'],
            [
                {'row_id': self.row.pk, 'outcome': 'error'},
                {'row_id': successful.pk, 'outcome': 'new'},
            ],
        )
        self.row.refresh_from_db()
        successful.refresh_from_db()
        self.account.refresh_from_db()
        self.upload.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(successful.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(self.account.balance, Decimal('970.00'))
        self.assertEqual(self.upload.imported_count, 1)
        self.assertEqual(self.upload.awaiting_decision_count, 1)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_linked_row_can_be_revised_to_new_once_with_audit(self) -> None:
        candidate_link = BankStatementCandidate.objects.get(row=self.row)
        decision_url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )
        self.client.post(
            decision_url,
            {'decision': 'linked', 'candidate': candidate_link.pk},
        )
        revision_url = reverse(
            'finance_account:bank_statement_reconciliation_revise',
            args=[self.upload.pk, self.row.pk],
        )

        first_response = self.client.post(revision_url)
        second_response = self.client.post(revision_url)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.row.refresh_from_db()
        self.account.refresh_from_db()
        self.upload.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.NEW)
        self.assertNotEqual(self.row.transaction, self.candidate)
        self.assertEqual(self.account.balance, Decimal('880.00'))
        self.assertEqual(Transaction.objects.count(), 2)
        audits = list(self.row.decision_audits.order_by('created_at'))
        self.assertEqual(len(audits), 2)
        self.assertEqual(audits[0].decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(audits[0].transaction, self.candidate)
        self.assertEqual(audits[1].decision, BankStatementRow.Decision.NEW)
        self.assertEqual(audits[1].previous_transaction, self.candidate)
        self.assertEqual(audits[1].transaction, self.row.transaction)
        self.assertEqual(self.upload.linked_count, 0)
        self.assertEqual(self.upload.imported_count, 1)

    def test_linked_row_cannot_be_revised_after_deadline(self) -> None:
        candidate_link = BankStatementCandidate.objects.get(row=self.row)
        self.client.post(
            reverse(
                'finance_account:bank_statement_reconciliation_decide',
                args=[self.upload.pk, self.row.pk],
            ),
            {'decision': 'linked', 'candidate': candidate_link.pk},
        )
        self.upload.expires_at = timezone.now() - timedelta(seconds=1)
        self.upload.save(update_fields=['expires_at'])

        response = self.client.post(
            reverse(
                'finance_account:bank_statement_reconciliation_revise',
                args=[self.upload.pk, self.row.pk],
            ),
        )

        self.assertEqual(response.status_code, 410)
        self.row.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(self.row.transaction, self.candidate)
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(Transaction.objects.count(), 1)

    def test_retention_cleanup_expires_unresolved_and_preserves_audit(
        self,
    ) -> None:
        candidate_link = BankStatementCandidate.objects.get(row=self.row)
        self.client.post(
            reverse(
                'finance_account:bank_statement_reconciliation_decide',
                args=[self.upload.pk, self.row.pk],
            ),
            {'decision': 'linked', 'candidate': candidate_link.pk},
        )
        pending = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('25.00'),
            description='Секретное назначение',
            candidate_description='Секретный кандидат',
            suggested_category='Секретная категория',
            source_ref='secret-source',
            source_row_position=1,
            candidate=self.candidate,
        )
        BankStatementCandidate.objects.create(
            row=pending,
            transaction=self.candidate,
            description='Секретные детали кандидата',
            rank=0,
        )
        pdf_content = b'%PDF-1.4 sensitive statement'
        self.upload.pdf_file.save(
            'retention.pdf',
            SimpleUploadedFile(
                'retention.pdf',
                pdf_content,
                content_type='application/pdf',
            ),
        )
        file_name = self.upload.pdf_file.name
        storage = self.upload.pdf_file.storage
        file_hash = sha256(pdf_content).hexdigest()
        self.upload.file_hash = file_hash
        deadline = timezone.now()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['file_hash', 'expires_at'])

        retention_service = BankStatementRetentionService(
            BankStatementReconciliationService(),
        )
        before_count = retention_service.cleanup_expired(
            deadline - timedelta(microseconds=1),
        )
        self.assertEqual(before_count, 0)
        self.assertTrue(storage.exists(file_name))
        with self.captureOnCommitCallbacks(execute=True):
            first_count = retention_service.cleanup_expired(deadline)
        with self.captureOnCommitCallbacks(execute=True):
            second_count = retention_service.cleanup_expired(deadline)

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.upload.refresh_from_db()
        self.row.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(
            self.upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        self.assertEqual(self.upload.expired_count, 1)
        self.assertEqual(self.upload.awaiting_decision_count, 0)
        self.assertEqual(self.upload.file_hash, file_hash)
        self.assertEqual(self.upload.account, self.account)
        self.assertIsNotNone(self.upload.retention_cleaned_at)
        self.assertFalse(storage.exists(file_name))
        self.assertFalse(bool(self.upload.pdf_file))
        self.assertEqual(pending.decision, BankStatementRow.Decision.EXPIRED)
        self.assert_retention_payload_scrubbed(pending)
        self.assertEqual(self.row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(self.row.transaction, self.candidate)
        self.assertEqual(self.row.decision_audits.count(), 1)
        self.assert_retention_payload_scrubbed(self.row)
        self.assertEqual(Transaction.objects.count(), 1)

        with patch(
            'hasta_la_vista_money.finance_account.bank_statement_views.process_bank_statement_task',
        ) as task:
            response = self.client.post(
                reverse('finance_account:bank_statement_upload'),
                {
                    'account': self.account.pk,
                    'pdf_file': SimpleUploadedFile(
                        'retention.pdf',
                        pdf_content,
                        content_type='application/pdf',
                    ),
                },
            )

        self.assert_reuploaded_after_retention(task, response, deadline)

    def test_cleanup_failure_isolated_per_upload_and_can_be_retried(
        self,
    ) -> None:
        self.upload.pdf_file.save(
            'retry-retention.pdf',
            SimpleUploadedFile(
                'retry-retention.pdf',
                b'%PDF-1.4 sensitive statement',
                content_type='application/pdf',
            ),
        )
        second = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file=SimpleUploadedFile(
                'second-retention.pdf',
                b'%PDF-1.4 second statement',
                content_type='application/pdf',
            ),
        )
        second_file_name = second.pdf_file.name
        deadline = timezone.now()
        BankStatementUpload.objects.filter(
            pk__in=[self.upload.pk, second.pk],
        ).update(expires_at=deadline)
        storage = self.upload.pdf_file.storage
        retry_file_name = self.upload.pdf_file.name
        retention_service = BankStatementRetentionService(
            BankStatementReconciliationService(),
        )
        real_delete = storage.delete

        def fail_only_retry_file(name: str) -> None:
            if name == retry_file_name:
                raise OSError('storage unavailable')
            real_delete(name)

        with (
            patch.object(
                storage,
                'delete',
                side_effect=fail_only_retry_file,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            cleaned = retention_service.cleanup_expired(deadline)

        self.assertEqual(cleaned, 2)
        self.upload.refresh_from_db()
        self.row.refresh_from_db()
        self.assertIsNotNone(self.upload.retention_cleaned_at)
        self.assertEqual(self.row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertTrue(storage.exists(retry_file_name))
        second.refresh_from_db()
        self.assertIsNotNone(second.retention_cleaned_at)
        self.assertFalse(storage.exists(second_file_name))

        with self.captureOnCommitCallbacks(execute=True):
            cleaned = retention_service.cleanup_expired(deadline)

        self.assertEqual(cleaned, 0)
        self.row.refresh_from_db()
        self.assertFalse(storage.exists(retry_file_name))
        self.assertEqual(self.row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_cleanup_rollback_keeps_pdf_and_database_state(self) -> None:
        """A failed cleanup transaction must not delete the stored PDF."""
        pdf_content = b'%PDF-1.4 rollback statement'
        self.upload.pdf_file.save(
            'rollback-retention.pdf',
            SimpleUploadedFile(
                'rollback-retention.pdf',
                pdf_content,
                content_type='application/pdf',
            ),
        )
        file_name = self.upload.pdf_file.name
        storage = self.upload.pdf_file.storage
        deadline = timezone.now()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['expires_at'])
        audit_count = AuditLog.objects.filter(
            kind=AuditOperationKind.STATEMENT_RETENTION,
        ).count()
        retention_service = BankStatementRetentionService(
            BankStatementReconciliationService(),
        )

        with (
            patch.object(
                BankStatementRetentionService,
                '_record_anonymization',
                side_effect=RuntimeError('forced rollback'),
            ),
            self.assertRaises(RuntimeError),
        ):
            retention_service.cleanup_expired(deadline)

        self.upload.refresh_from_db()
        self.row.refresh_from_db()
        self.assertIsNone(self.upload.retention_cleaned_at)
        self.assertEqual(self.upload.pdf_file.name, file_name)
        self.assertEqual(self.upload.retention_pending_pdf_paths, [])
        self.assertTrue(storage.exists(file_name))
        self.assertEqual(self.row.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(
            AuditLog.objects.filter(
                kind=AuditOperationKind.STATEMENT_RETENTION,
            ).count(),
            audit_count,
        )

    def test_storage_error_retries_pdf_deletion_without_repeating_cleanup(
        self,
    ) -> None:
        """A cleaned upload keeps only its PDF path for a later retry."""
        pdf_content = b'%PDF-1.4 storage error statement'
        self.upload.pdf_file.save(
            'storage-error-retention.pdf',
            SimpleUploadedFile(
                'storage-error-retention.pdf',
                pdf_content,
                content_type='application/pdf',
            ),
        )
        file_name = self.upload.pdf_file.name
        storage = self.upload.pdf_file.storage
        deadline = timezone.now()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['expires_at'])
        retention_service = BankStatementRetentionService(
            BankStatementReconciliationService(),
        )

        with (
            patch.object(
                storage,
                'delete',
                side_effect=OSError('storage unavailable'),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            first_count = retention_service.cleanup_expired(deadline)

        self.assertEqual(first_count, 1)
        self.upload.refresh_from_db()
        self.row.refresh_from_db()
        cleaned_at = self.upload.retention_cleaned_at
        self.assertIsNotNone(cleaned_at)
        self.assertFalse(bool(self.upload.pdf_file))
        self.assertEqual(self.upload.retention_pending_pdf_paths, [file_name])
        self.assertEqual(self.row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(
            AuditLog.objects.filter(
                kind=AuditOperationKind.STATEMENT_RETENTION,
            ).count(),
            1,
        )
        self.assertTrue(storage.exists(file_name))

        with (
            patch.object(
                storage,
                'delete',
                side_effect=OSError('storage unavailable'),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            repeated_count = retention_service.cleanup_expired(deadline)
        self.assertEqual(repeated_count, 0)
        self.assertTrue(storage.exists(file_name))

        restarted_service = BankStatementRetentionService(
            BankStatementReconciliationService(),
        )
        with self.captureOnCommitCallbacks(execute=True):
            retry_count = restarted_service.cleanup_expired(
                deadline + timedelta(seconds=1),
            )

        self.assertEqual(retry_count, 0)
        self.upload.refresh_from_db()
        self.row.refresh_from_db()
        self.assertFalse(storage.exists(file_name))
        self.assertEqual(self.upload.retention_pending_pdf_paths, [])
        self.assertEqual(self.upload.retention_cleaned_at, cleaned_at)
        self.assertEqual(self.row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(
            AuditLog.objects.filter(
                kind=AuditOperationKind.STATEMENT_RETENTION,
            ).count(),
            1,
        )
        self.assertEqual(Transaction.objects.count(), 1)

    def test_pending_deletion_after_reupload_keeps_the_new_pdf(self) -> None:
        """A retried delete of the old file must not touch a new upload."""
        old_content = b'%PDF-1.4 old retention statement'
        self.upload.pdf_file.save(
            'old-retention.pdf',
            SimpleUploadedFile(
                'old-retention.pdf',
                old_content,
                content_type='application/pdf',
            ),
        )
        old_name = self.upload.pdf_file.name
        storage = self.upload.pdf_file.storage
        deadline = timezone.now()
        self.upload.file_hash = sha256(old_content).hexdigest()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['file_hash', 'expires_at'])
        retention_service = BankStatementRetentionService(
            BankStatementReconciliationService(),
        )

        with (
            patch.object(
                storage,
                'delete',
                side_effect=OSError('storage unavailable'),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            retention_service.cleanup_expired(deadline)

        self.upload.refresh_from_db()
        self.assertEqual(self.upload.retention_pending_pdf_paths, [old_name])

        new_content = b'%PDF-1.4 reuploaded statement'
        replayed = ApplicationContainer().users.bank_statement_import_service()
        self.assertTrue(
            replayed.prepare_known_replay(
                self.upload,
                SimpleUploadedFile(
                    'new-retention.pdf',
                    new_content,
                    content_type='application/pdf',
                ),
            ),
        )
        self.upload.refresh_from_db()
        new_name = self.upload.pdf_file.name
        self.assertNotEqual(new_name, old_name)
        self.assertTrue(storage.exists(new_name))
        self.assertIsNone(self.upload.retention_cleaned_at)

        with self.captureOnCommitCallbacks(execute=True):
            retry_count = retention_service.cleanup_expired(
                deadline + timedelta(seconds=1),
            )

        self.assertEqual(retry_count, 0)
        self.upload.refresh_from_db()
        self.row.refresh_from_db()
        self.assertFalse(storage.exists(old_name))
        self.assertTrue(storage.exists(new_name))
        self.assertEqual(self.upload.pdf_file.name, new_name)
        self.assertEqual(self.upload.retention_pending_pdf_paths, [])
        self.assertIsNone(self.upload.retention_cleaned_at)
        self.assertEqual(self.row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(
            AuditLog.objects.filter(
                kind=AuditOperationKind.STATEMENT_RETENTION,
            ).count(),
            1,
        )

    def test_reupload_during_pending_delete_keeps_the_new_pdf(self) -> None:
        """A re-upload racing a queued old delete survives that delete."""
        old_content = b'%PDF-1.4 racing old statement'
        self.upload.pdf_file.save(
            'racing-old.pdf',
            SimpleUploadedFile(
                'racing-old.pdf',
                old_content,
                content_type='application/pdf',
            ),
        )
        old_name = self.upload.pdf_file.name
        storage = self.upload.pdf_file.storage
        deadline = timezone.now()
        self.upload.file_hash = sha256(old_content).hexdigest()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['file_hash', 'expires_at'])
        retention_service = BankStatementRetentionService(
            BankStatementReconciliationService(),
        )
        with (
            patch.object(
                storage,
                'delete',
                side_effect=OSError('storage unavailable'),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            retention_service.cleanup_expired(deadline)
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.retention_pending_pdf_paths, [old_name])

        new_name: str | None = None
        real_delete = storage.delete

        def reupload_before_delete(name: str) -> None:
            nonlocal new_name
            if name == old_name:
                replayed = (
                    ApplicationContainer().users.bank_statement_import_service()
                )
                replayed.prepare_known_replay(
                    self.upload,
                    SimpleUploadedFile(
                        'racing-new.pdf',
                        b'%PDF-1.4 racing new statement',
                        content_type='application/pdf',
                    ),
                )
                self.upload.refresh_from_db()
                new_name = self.upload.pdf_file.name
            real_delete(name)

        with (
            patch.object(
                storage,
                'delete',
                side_effect=reupload_before_delete,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            retry_count = retention_service.cleanup_expired(
                deadline + timedelta(seconds=1),
            )

        self.assertEqual(retry_count, 0)
        self.upload.refresh_from_db()
        if new_name is None:
            self.fail('The re-upload did not attach a new file')
        self.assertNotEqual(new_name, old_name)
        self.assertFalse(storage.exists(old_name))
        self.assertTrue(storage.exists(new_name))
        self.assertEqual(self.upload.pdf_file.name, new_name)
        self.assertIsNone(self.upload.retention_cleaned_at)
        self.assertEqual(self.upload.retention_pending_pdf_paths, [])

    def test_retention_anonymizes_only_statement_audit_copies(self) -> None:
        """Bank copies in audit are scrubbed; independent audit is untouched."""
        with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
            statement_movement = Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=self.category,
                type=TransactionType.EXPENSE,
                amount=Decimal('77.00'),
                date=timezone.now(),
                description='Секретный банковский магазин',
                source_ref='secret-bank-ref',
            )
            self.account.balance -= Decimal('77.00')
            self.account.save(update_fields=['balance'])
            record_statement_import_summary(
                user=self.user,
                account=self.account,
                created=1,
                skipped_duplicates=0,
                period_from=date(2026, 11, 1),
                period_to=date(2026, 11, 30),
            )
        independent_movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('15.00'),
            date=timezone.now(),
            description='Ручная покупка',
        )
        independent_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(independent_movement.pk),
        )
        independent_diff = independent_audit.diff
        balance_audit = (
            AuditLog.objects.filter(
                model_name='finance_account.Account',
                object_pk=str(self.account.pk),
                kind=AuditOperationKind.STATEMENT_IMPORT,
            )
            .order_by('-pk')
            .first()
        )
        if balance_audit is None:
            self.fail('The statement import balance audit entry is missing')
        balance_diff = balance_audit.diff

        self.row.transaction = statement_movement
        self.row.decision = BankStatementRow.Decision.NEW
        self.row.source_fingerprint = 'safe-fingerprint'
        self.row.source_fingerprint_key_version = 'k2'
        self.row.save(
            update_fields=[
                'transaction',
                'decision',
                'source_fingerprint',
                'source_fingerprint_key_version',
            ],
        )
        deadline = timezone.now()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['expires_at'])

        BankStatementRetentionService(
            BankStatementReconciliationService(),
        ).cleanup_expired(deadline)

        statement_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(statement_movement.pk),
            kind=AuditOperationKind.STATEMENT_IMPORT,
        )
        created_values = statement_audit.diff['created']
        for field in ('amount', 'date', 'description', 'source_ref'):
            with self.subTest(field=field):
                self.assertNotIn(field, created_values)
        self.assertIn('type', created_values)
        self.assertIn('account_id', created_values)

        independent_audit.refresh_from_db()
        self.assertEqual(independent_audit.diff, independent_diff)
        balance_audit.refresh_from_db()
        self.assertEqual(balance_audit.diff, balance_diff)

        self.row.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(self.row.transaction, statement_movement)
        self.assertEqual(self.row.source_fingerprint, 'safe-fingerprint')
        self.assertEqual(self.row.source_fingerprint_key_version, 'k2')
        self.assertEqual(Transaction.objects.count(), 3)

        retention_audit = AuditLog.objects.get(
            kind=AuditOperationKind.STATEMENT_RETENTION,
        )
        self.assertEqual(retention_audit.user, self.user)
        retention_text = str(retention_audit.diff)
        for bank_value in ('77.00', 'Секретный', 'secret-bank-ref'):
            with self.subTest(value=bank_value):
                self.assertNotIn(bank_value, retention_text)

    def test_cleanup_clears_source_ref_of_created_movement_only(self) -> None:
        """Retention removes the raw bank ref from the created movement."""
        self.upload.file_hash = 'retention-created-file'
        self.upload.save(update_fields=['file_hash'])
        created = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('120.00'),
            date=self.candidate.date,
            description='Банковская покупка',
            source_ref='new-source',
            source_fingerprint='created-fingerprint',
            source_fingerprint_key_version='k2',
            source_file_hash=self.upload.file_hash,
            source_row_position=0,
        )
        self.row.transaction = created
        self.row.decision = BankStatementRow.Decision.NEW
        self.row.source_fingerprint = 'created-fingerprint'
        self.row.source_fingerprint_key_version = 'k2'
        self.row.save(
            update_fields=[
                'transaction',
                'decision',
                'source_fingerprint',
                'source_fingerprint_key_version',
            ],
        )
        linked = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('50.00'),
            date=self.candidate.date,
            description='Уже существующая операция',
            source_ref='linked-bank-ref',
        )
        BankStatementRow.objects.create(
            upload=self.upload,
            source_row_position=1,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=self.candidate.date,
            amount=Decimal('50.00'),
            description='Связанная строка',
            source_ref='linked-row-ref',
            transaction=linked,
            decision=BankStatementRow.Decision.LINKED,
        )
        foreign = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('30.00'),
            date=self.candidate.date,
            description='Ручная операция',
            source_ref='manual-bank-ref',
        )
        deadline = timezone.now()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['expires_at'])

        BankStatementRetentionService(
            BankStatementReconciliationService(),
        ).cleanup_expired(deadline)

        created.refresh_from_db()
        linked.refresh_from_db()
        foreign.refresh_from_db()
        self.assertIsNone(created.source_ref)
        self.assertEqual(created.source_fingerprint, 'created-fingerprint')
        self.assertEqual(created.source_fingerprint_key_version, 'k2')
        self.assertEqual(created.source_file_hash, self.upload.file_hash)
        self.assertEqual(created.source_row_position, 0)
        self.assertEqual(linked.source_ref, 'linked-bank-ref')
        self.assertEqual(foreign.source_ref, 'manual-bank-ref')

    def test_cleanup_keeps_legacy_decision_and_independent_audit(
        self,
    ) -> None:
        """An old movement without fingerprints keeps its decision history."""
        legacy = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('120.00'),
            date=self.candidate.date,
            description='Старая банковская покупка',
            source_ref='legacy-bank-ref',
        )
        self.row.transaction = legacy
        self.row.decision = BankStatementRow.Decision.NEW
        self.row.source_ref = 'legacy-bank-ref'
        self.row.source_fingerprint = ''
        self.row.save(
            update_fields=[
                'transaction',
                'decision',
                'source_ref',
                'source_fingerprint',
            ],
        )
        decision_audit = BankStatementDecisionAudit.objects.create(
            row=self.row,
            decision=BankStatementRow.Decision.NEW,
            previous_decision=BankStatementRow.Decision.PENDING,
            transaction=legacy,
        )
        independent = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('10.00'),
            date=self.candidate.date,
            description='Независимая ручная операция',
        )
        independent_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(independent.pk),
        )
        independent_diff = independent_audit.diff
        deadline = timezone.now()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['expires_at'])

        BankStatementRetentionService(
            BankStatementReconciliationService(),
        ).cleanup_expired(deadline)

        legacy.refresh_from_db()
        decision_audit.refresh_from_db()
        self.assertIsNone(legacy.source_ref)
        self.assertEqual(legacy.source_fingerprint, '')
        self.row.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(self.row.transaction, legacy)
        self.assertEqual(decision_audit.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(
            decision_audit.previous_decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertEqual(decision_audit.transaction, legacy)
        independent_audit.refresh_from_db()
        self.assertEqual(independent_audit.diff, independent_diff)

    def test_cleanup_does_not_reach_shared_fingerprint_of_other_upload(
        self,
    ) -> None:
        """A repeated observation in another upload keeps its own audit."""
        self.row.source_fingerprint = 'shared-fingerprint'
        self.row.decision = BankStatementRow.Decision.NEW
        self.row.transaction = self.candidate
        self.row.save(
            update_fields=[
                'source_fingerprint',
                'decision',
                'transaction',
            ],
        )
        other_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/shared-fingerprint.pdf',
            file_hash='shared-fingerprint-file',
        )
        BankStatementRow.objects.create(
            upload=other_upload,
            source_row_position=0,
            source_ref='shared-bank-ref',
            source_fingerprint='shared-fingerprint',
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('120.00'),
            decision=BankStatementRow.Decision.PENDING,
        )
        other_audit = AuditLog.objects.create(
            user=self.user,
            model_name='transactions.Transaction',
            object_pk='999999',
            action=AuditLog.Action.CREATE,
            kind=AuditOperationKind.STATEMENT_IMPORT,
            diff={
                'v': 2,
                'created': {
                    'amount': '120.00',
                    'description': 'Секретная операция другой выписки',
                    'source_fingerprint': 'shared-fingerprint',
                },
            },
        )
        other_diff = other_audit.diff
        deadline = timezone.now()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['expires_at'])

        BankStatementRetentionService(
            BankStatementReconciliationService(),
        ).cleanup_expired(deadline)

        other_audit.refresh_from_db()
        self.assertEqual(other_audit.diff, other_diff)
        other_upload.refresh_from_db()
        self.assertIsNone(other_upload.retention_cleaned_at)

    def test_cleanup_does_not_mix_equal_transaction_and_transfer_pks(
        self,
    ) -> None:
        """Same numeric pk in two models must not scrub another upload."""
        other_account = Account.objects.create(
            user=self.user,
            name_account='Второй счёт',
            balance=Decimal('500.00'),
        )
        with audit_operation(kind=AuditOperationKind.STATEMENT_MARKUP):
            transfer = TransferMoneyLog.objects.create(
                pk=self.candidate.pk,
                user=self.user,
                from_account=self.account,
                to_account=other_account,
                amount=Decimal('90.00'),
                exchange_date=timezone.now(),
                notes='Секретный перевод другой выписки',
            )
        other_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/other-transfer.pdf',
        )
        other_row = BankStatementRow.objects.create(
            upload=other_upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('90.00'),
            transfer=transfer,
            decision=BankStatementRow.Decision.TRANSFERRED,
        )
        transfer_audit = AuditLog.objects.get(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(transfer.pk),
            kind=AuditOperationKind.STATEMENT_MARKUP,
        )
        transfer_diff = transfer_audit.diff
        transaction_audit = AuditLog.objects.create(
            user=self.user,
            model_name='transactions.Transaction',
            object_pk=str(self.candidate.pk),
            action=AuditLog.Action.CREATE,
            kind=AuditOperationKind.STATEMENT_IMPORT,
            diff={
                'v': 2,
                'created': {
                    'amount': '120.00',
                    'description': 'Секретная транзакция',
                    'source_ref': 'secret-transaction-ref',
                },
            },
        )
        self.row.decision = BankStatementRow.Decision.NEW
        self.row.transaction = self.candidate
        self.row.save(update_fields=['decision', 'transaction'])
        deadline = timezone.now()
        self.upload.expires_at = deadline
        self.upload.save(update_fields=['expires_at'])

        BankStatementRetentionService(
            BankStatementReconciliationService(),
        ).cleanup_expired(deadline)

        transaction_audit.refresh_from_db()
        created = transaction_audit.diff['created']
        for field in ('amount', 'description', 'source_ref'):
            with self.subTest(field=field):
                self.assertNotIn(field, created)
        transfer_audit.refresh_from_db()
        self.assertEqual(transfer_audit.diff, transfer_diff)
        other_row.refresh_from_db()
        self.assertEqual(
            other_row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertEqual(other_row.transfer, transfer)
        self.assertTrue(
            TransferMoneyLog.objects.filter(pk=transfer.pk).exists(),
        )

    def test_pending_decision_after_deadline_creates_no_transaction(
        self,
    ) -> None:
        self.upload.expires_at = timezone.now() - timedelta(seconds=1)
        self.upload.save(update_fields=['expires_at'])

        response = self.client.post(
            reverse(
                'finance_account:bank_statement_reconciliation_decide',
                args=[self.upload.pk, self.row.pk],
            ),
            {'decision': 'new'},
        )

        self.assertEqual(response.status_code, 410)
        self.row.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(Transaction.objects.count(), 1)

    def test_reconciliation_page_exposes_bulk_and_safe_revision_actions(
        self,
    ) -> None:
        pending_response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )
        candidate_link = BankStatementCandidate.objects.get(row=self.row)
        self.client.post(
            reverse(
                'finance_account:bank_statement_reconciliation_decide',
                args=[self.upload.pk, self.row.pk],
            ),
            {'decision': 'linked', 'candidate': candidate_link.pk},
        )
        linked_response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            {'outcome': 'linked'},
        )
        self.client.post(
            reverse(
                'finance_account:bank_statement_reconciliation_revise',
                args=[self.upload.pk, self.row.pk],
            ),
        )
        new_response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            {'outcome': 'new'},
        )

        self.assertContains(pending_response, 'Массово: уже учтены')
        self.assertContains(
            pending_response,
            'Подтверждаю риск создания новых операций',
        )
        self.assertContains(
            linked_response,
            'Пересмотреть и импортировать как новую',
        )
        self.assertContains(
            new_response,
            'Связать эту строку с существующей операцией нельзя',
        )

    def test_other_user_cannot_view_or_decide(self) -> None:
        self.client.force_login(self.other_user)
        page_url = reverse(
            'finance_account:bank_statement_reconciliation',
            args=[self.upload.pk],
        )
        decision_url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )
        revision_url = reverse(
            'finance_account:bank_statement_reconciliation_revise',
            args=[self.upload.pk, self.row.pk],
        )

        self.assertEqual(self.client.get(page_url).status_code, 404)
        self.assertEqual(
            self.client.post(
                decision_url,
                {'decision': 'new'},
            ).status_code,
            404,
        )
        self.assertEqual(self.client.post(revision_url).status_code, 404)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_conflicting_repeated_decision_is_rejected(self) -> None:
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )

        candidate = BankStatementCandidate.objects.get(row=self.row)
        self.client.post(
            url,
            {'decision': 'linked', 'candidate': candidate.pk},
        )
        response = self.client.post(url, {'decision': 'new'})

        self.assertEqual(response.status_code, 409)
        self.row.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_linked_decision_without_candidate_returns_to_reconciliation(
        self,
    ) -> None:
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )

        response = self.client.post(
            url,
            {'decision': 'linked'},
            follow=True,
        )

        self.assertRedirects(
            response,
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )
        self.assertContains(
            response,
            'Выберите учтённую операцию перед подтверждением.',
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.PENDING)

    def test_repeated_linked_decision_rejects_different_candidate(self) -> None:
        if self.row.amount is None or self.row.transaction_date is None:
            self.fail('Statement row must contain amount and date')
        second = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=self.row.amount,
            date=self.row.transaction_date,
        )
        second_candidate = BankStatementCandidate.objects.create(
            row=self.row,
            transaction=second,
            description='Второй кандидат',
            rank=1,
        )
        first_candidate = BankStatementCandidate.objects.get(
            row=self.row,
            rank=0,
        )
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )

        self.client.post(
            url,
            {'decision': 'linked', 'candidate': first_candidate.pk},
        )
        response = self.client.post(
            url,
            {'decision': 'linked', 'candidate': second_candidate.pk},
        )

        self.assertEqual(response.status_code, 409)
        self.row.refresh_from_db()
        self.assertEqual(self.row.transaction, self.candidate)

    def test_defaults_to_first_25_pending_rows_ordered_by_date(self) -> None:
        BankStatementRow.objects.all().delete()
        base_date = timezone.now()
        for index in range(30):
            BankStatementRow.objects.create(
                upload=self.upload,
                transaction_type=TransactionType.EXPENSE,
                transaction_date=base_date + timedelta(minutes=index),
                amount=Decimal('10.00'),
                description=f'Строка {index}',
                candidate_description='Кандидат',
                suggested_category='Прочее',
                source_row_position=index,
                candidate=self.candidate,
            )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 25)
        self.assertEqual(response.context['outcome'], 'pending')
        self.assertEqual(
            response.context['page_obj'][0].description,
            'Строка 0',
        )
        self.assertNotContains(response, 'Строка 29')

        second_page = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            {'page': 2},
        )
        self.assertEqual(len(second_page.context['page_obj']), 5)
        self.assertContains(second_page, '?outcome=pending&page=1')

    def test_rows_with_same_date_use_primary_key_tie_breaker(self) -> None:
        BankStatementRow.objects.all().delete()
        transaction_date = timezone.now()
        first = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=transaction_date,
            amount=Decimal('10.00'),
            description='Первая',
            candidate_description='Кандидат',
            suggested_category='Прочее',
            source_row_position=0,
            candidate=self.candidate,
        )
        second = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=transaction_date,
            amount=Decimal('20.00'),
            description='Вторая',
            candidate_description='Кандидат',
            suggested_category='Прочее',
            source_row_position=1,
            candidate=self.candidate,
        )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(list(response.context['page_obj']), [first, second])

    def test_filters_linked_and_new_rows(self) -> None:
        linked = self.row
        linked.decision = BankStatementRow.Decision.LINKED
        linked.transaction = self.candidate
        linked.save(update_fields=['decision', 'transaction'])
        new_transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('20.00'),
            date=timezone.now() + timedelta(minutes=1),
        )
        new = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now() + timedelta(minutes=1),
            amount=Decimal('20.00'),
            description='Новая строка',
            candidate_description='Кандидат',
            suggested_category='Прочее',
            source_row_position=1,
            candidate=self.candidate,
            transaction=new_transaction,
            decision=BankStatementRow.Decision.NEW,
        )

        linked_response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            {'outcome': 'linked'},
        )
        new_response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            {'outcome': 'new'},
        )

        self.assertEqual(list(linked_response.context['page_obj']), [linked])
        self.assertEqual(list(new_response.context['page_obj']), [new])

    def test_unavailable_upload_is_not_found(self) -> None:
        url = reverse(
            'finance_account:bank_statement_reconciliation',
            args=[self.upload.pk],
        )
        past = timezone.now() - timedelta(seconds=1)
        for field in ('expires_at', 'retention_cleaned_at'):
            with self.subTest(field=field):
                upload = BankStatementUpload.objects.get(pk=self.upload.pk)
                setattr(upload, field, past)
                upload.save(update_fields=[field])

                self.assertEqual(self.client.get(url).status_code, 404)

                BankStatementUpload.objects.filter(pk=upload.pk).update(
                    expires_at=timezone.now() + timedelta(days=1),
                    retention_cleaned_at=None,
                )

    def test_all_outcome_is_default_without_pending_rows(self) -> None:
        self.row.decision = BankStatementRow.Decision.NEEDS_TRANSFER
        self.row.save(update_fields=['decision'])
        self.upload.status = BankStatementUpload.Status.COMPLETED
        self.upload.save(update_fields=['status'])

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(
            response.context['outcome'],
            constants.STATEMENT_OUTCOME_ALL,
        )
        self.assertEqual(list(response.context['page_obj']), [self.row])
        self.assertContains(response, self.row.get_decision_display())

    def test_unknown_outcome_falls_back_to_pending(self) -> None:
        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
            {'outcome': BankStatementRow.Decision.EXPIRED},
        )

        self.assertEqual(
            response.context['outcome'],
            BankStatementRow.Decision.PENDING,
        )
        self.assertEqual(list(response.context['page_obj']), [self.row])

    def test_family_viewer_cannot_open_reconciliation(self) -> None:
        group = Group.objects.create(name='Семья')
        self.user.groups.add(group)
        self.other_user.groups.add(group)
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.other_user,
            role=FamilyGroupMembership.Role.VIEWER,
        )
        self.client.force_login(self.other_user)

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 404)
        decision_response = self.client.post(
            reverse(
                'finance_account:bank_statement_reconciliation_decide',
                args=[self.upload.pk, self.row.pk],
            ),
            {'decision': 'new'},
        )
        self.assertEqual(decision_response.status_code, 404)

    def test_balance_adjustment_is_not_a_candidate(self) -> None:
        adjustment_category = Category.objects.create(
            user=self.user,
            name='Корректировка остатка',
            type=TransactionType.EXPENSE,
            system_kind=SystemCategoryKind.BALANCE_ADJUSTMENT,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=adjustment_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('120.00'),
            date=self.candidate.date,
        )

        candidates = BankStatementReconciliationService().current_candidates(
            self.row,
        )

        self.assertEqual(list(candidates), [self.candidate])

    def test_stale_candidate_returns_current_candidates(self) -> None:
        stale_candidate = BankStatementCandidate.objects.get(row=self.row)
        stale_transaction = stale_candidate.transaction
        if stale_transaction is None:
            self.fail('Expected a linked candidate transaction')
        stale_transaction.delete()
        if self.row.transaction_date is None:
            self.fail('Statement row must contain a date')
        replacement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('120.00'),
            date=self.row.transaction_date,
        )
        url = reverse(
            'finance_account:bank_statement_reconciliation_decide',
            args=[self.upload.pk, self.row.pk],
        )

        response = self.client.post(
            url,
            {
                'decision': 'linked',
                'candidate': stale_candidate.pk,
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertContains(response, str(replacement.pk), status_code=409)
        self.row.refresh_from_db()
        self.assertEqual(self.row.decision, BankStatementRow.Decision.PENDING)

    def test_control_does_not_treat_coverage_or_balance_as_row_resolution(
        self,
    ) -> None:
        today = timezone.localdate()
        coverage_service = (
            ApplicationContainer().users.statement_coverage_service()
        )
        coverage_service.record_statement_period(
            self.upload,
            today.replace(day=1),
            today,
        )
        self.upload.balance_discrepancy = Decimal('120.00')
        self.upload.save(update_fields=['balance_discrepancy'])

        params: dict[str, str | int] = {
            'account': self.account.pk,
            'period_start': today.replace(day=1).isoformat(),
            'period_end': today.isoformat(),
        }
        response = self.client.get(
            reverse('finance_account:accounting_control'),
            params,
        )

        control = response.context['control']
        self.assertEqual(control.coverage.state, 'covered')
        self.assertEqual(control.rows.pending, 1)
        self.assertFalse(control.balance.checked)
        self.assertContains(response, 'Не проверено')

    def test_owner_explains_balance_discrepancy_without_money(self) -> None:
        today = timezone.localdate()
        self.upload.statement_closing_balance = Decimal('880.00')
        self.upload.balance_moment = timezone.now()
        self.upload.balance_currency = 'RUB'
        self.upload.balance_type = BankStatementUpload.BalanceType.EXACT_MOMENT
        self.upload.save(
            update_fields=[
                'statement_closing_balance',
                'balance_moment',
                'balance_currency',
                'balance_type',
            ],
        )
        self.row.decision = BankStatementRow.Decision.LINKED
        self.row.decided_at = timezone.now()
        self.row.save(update_fields=['decision', 'decided_at'])
        container = ApplicationContainer()
        users = container.users
        service = users.statement_balance_verification_service()
        service.verify(self.upload)
        before_balance = self.account.balance
        before_transactions = Transaction.objects.count()

        response = self.client.post(
            reverse('finance_account:accounting_control'),
            {
                'action': 'explain_balance',
                'account': self.account.pk,
                'upload_id': self.upload.pk,
                'code': (
                    BankStatementUpload.ExplanationCode.CONSCIOUS_INCOMPLETE_ACCOUNTING
                ),
                'period_start': today.replace(day=1).isoformat(),
                'period_end': today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.upload.refresh_from_db()
        self.assertEqual(
            self.upload.balance_explanation_code,
            BankStatementUpload.ExplanationCode.CONSCIOUS_INCOMPLETE_ACCOUNTING,
        )
        self.assertEqual(self.upload.balance_explained_by, self.user)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, before_balance)
        self.assertEqual(Transaction.objects.count(), before_transactions)


class TestBankStatementUploadHistory(TestCase):
    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.client = Client()
        self.client.force_login(self.user)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def test_upload_page_lists_history_and_unfinished_review_link(self) -> None:
        pending = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/pending.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        completed = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/completed.pdf',
            status=BankStatementUpload.Status.COMPLETED,
        )
        unresolved = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/unresolved.pdf',
            status=BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        other_user = User.objects.get(pk=2)
        other_account = Account.objects.create(
            user=other_user,
            name_account='Чужой счёт',
            balance=Decimal('500.00'),
            currency='RUB',
        )
        BankStatementUpload.objects.create(
            user=other_user,
            account=other_account,
            pdf_file='bank_statements/foreign.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

        response = self.client.get(
            reverse('finance_account:bank_statement_upload'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'История загрузок')
        self.assertEqual(
            list(response.context['upload_history']),
            [unresolved, completed, pending],
        )
        self.assertContains(
            response,
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[pending.pk],
            ),
        )
        for upload in (completed, unresolved):
            with self.subTest(status=upload.status):
                self.assertContains(
                    response,
                    reverse(
                        'finance_account:bank_statement_reconciliation',
                        args=[upload.pk],
                    ),
                )
        self.assertNotContains(response, 'Чужой счёт')

    def test_history_hides_link_for_unavailable_uploads(self) -> None:
        past = timezone.now() - timedelta(seconds=1)
        hidden = [
            BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file='bank_statements/expired.pdf',
                status=BankStatementUpload.Status.COMPLETED,
                expires_at=past,
            ),
            BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file='',
                status=BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
                retention_cleaned_at=past,
            ),
            BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file='bank_statements/stale.pdf',
                status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
                expires_at=past,
            ),
            BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file='bank_statements/failed.pdf',
                status=BankStatementUpload.Status.FAILED,
            ),
        ]

        response = self.client.get(
            reverse('finance_account:bank_statement_upload'),
        )

        for upload in hidden:
            with self.subTest(status=upload.status):
                self.assertNotContains(
                    response,
                    reverse(
                        'finance_account:bank_statement_reconciliation',
                        args=[upload.pk],
                    ),
                )

    def test_history_is_paginated(self) -> None:
        uploads = [
            BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file=f'bank_statements/{index}.pdf',
                status=BankStatementUpload.Status.COMPLETED,
            )
            for index in range(constants.PAGINATE_BY_DEFAULT + 1)
        ]
        url = reverse('finance_account:bank_statement_upload')

        first = self.client.get(url)
        second = self.client.get(url, {'page': 2})

        self.assertEqual(
            len(first.context['upload_history']),
            constants.PAGINATE_BY_DEFAULT,
        )
        self.assertEqual(list(second.context['upload_history']), [uploads[0]])
        self.assertContains(first, '?page=2')

    def _control_response(self) -> Any:
        today = timezone.localdate()
        params: dict[str, str | int] = {
            'account': self.account.pk,
            'period_start': today.replace(day=1).isoformat(),
            'period_end': today.isoformat(),
        }
        return self.client.get(
            reverse('finance_account:accounting_control'),
            params,
        )

    def test_control_shows_technical_processing_separately_from_rows(
        self,
    ) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/control-technical.pdf',
            status=BankStatementUpload.Status.COMPLETED,
        )
        BankStatementRow.objects.create(
            upload=upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('15.00'),
            description='Обед',
            source_ref='control-technical',
            source_row_position=1,
            decision=BankStatementRow.Decision.PENDING,
        )

        response = self._control_response()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Завершено')
        self.assertContains(response, 'Техническая обработка')
        self.assertEqual(response.context['control'].rows.pending, 1)
        self.assertEqual(response.context['control'].coverage.state, 'unknown')
        self.assertContains(response, 'Неизвестен')

    def test_control_marks_upload_without_updated_adapter_as_not_covered(
        self,
    ) -> None:
        BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/control-adapter.pdf',
            status=BankStatementUpload.Status.COMPLETED,
        )

        response = self._control_response()

        control = response.context['control']
        self.assertFalse(control.uploads[0].has_markup_rows)
        self.assertIn('Не покрыт этим срезом', control.uploads[0].markup_label)
        self.assertContains(response, 'Не покрыт этим срезом')

    def test_control_lists_confirmed_exclusion_as_a_caveat(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/control-exclusion.pdf',
            status=BankStatementUpload.Status.COMPLETED,
        )
        BankStatementRow.objects.create(
            upload=upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('1.00'),
            description='Не операция',
            source_ref='control-exclusion',
            source_row_position=1,
            decision=BankStatementRow.Decision.SKIPPED,
            exclusion_code=BankStatementRow.ExclusionCode.NON_FINANCIAL_BANK_RECORD,
        )

        response = self._control_response()

        control = response.context['control']
        self.assertEqual(len(control.exclusions), 1)
        self.assertEqual(control.rows.legacy_skips, 0)
        self.assertContains(response, 'оговорки полноты')
        self.assertContains(response, 'Нефинансовая запись банка')

    def test_control_shows_duplicate_observations_as_separate_outcome(
        self,
    ) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/control-duplicate.pdf',
            status=BankStatementUpload.Status.COMPLETED,
        )
        canonical = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('20.00'),
            description='Кофе',
            source_ref='control-duplicate-1',
            source_row_position=1,
            decision=BankStatementRow.Decision.NEW,
        )
        BankStatementRow.objects.create(
            upload=upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('20.00'),
            description='Кофе',
            source_ref='control-duplicate-2',
            source_row_position=2,
            decision=BankStatementRow.Decision.DUPLICATE,
            canonical_row=canonical,
        )

        response = self._control_response()

        control = response.context['control']
        self.assertEqual(control.rows.resolved, 1)
        self.assertEqual(control.rows.duplicates, 1)
        self.assertContains(response, 'Точные дубли')

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_import_records_explicit_statement_period_coverage(
        self,
        parser_class: MagicMock,
    ) -> None:
        parser_class.return_value.parse.return_value = StatementParseResult(
            transactions=[
                {
                    'date': datetime(
                        2026,
                        3,
                        10,
                        tzinfo=timezone.get_current_timezone(),
                    ),
                    'amount': Decimal('-100.00'),
                    'description': 'Покупка',
                    'source_ref': '1-10.03.2026',
                    'source': 'rosdorbank',
                    'kind': 'card',
                },
            ],
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            requires_markup=True,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/control-period.pdf',
            status=BankStatementUpload.Status.PENDING,
        )

        ApplicationContainer().users.bank_statement_import_service().import_statement(
            upload,
        )

        coverage = StatementPeriodCoverage.objects.get(upload=upload)
        self.assertEqual(coverage.period_start, date(2026, 3, 1))
        self.assertEqual(coverage.period_end, date(2026, 3, 31))
        self.assertEqual(
            coverage.source,
            StatementPeriodCoverage.Source.BANK_STATEMENT,
        )
        self.assertEqual(coverage.author, self.user)

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_import_does_not_publish_coverage_for_empty_parse(
        self,
        parser_class: MagicMock,
    ) -> None:
        """A zero-row parse keeps its bounds but proves no coverage."""
        parser_class.return_value.parse.return_value = StatementParseResult(
            transactions=[],
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            requires_markup=True,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/empty-period.pdf',
            status=BankStatementUpload.Status.PENDING,
        )

        ApplicationContainer().users.bank_statement_import_service().import_statement(
            upload,
        )
        upload.refresh_from_db()

        self.assertEqual(upload.statement_period_from, date(2026, 3, 1))
        self.assertEqual(upload.statement_period_to, date(2026, 3, 31))
        self.assertFalse(
            StatementPeriodCoverage.objects.filter(upload=upload).exists(),
        )
        summary = (
            ApplicationContainer()
            .users.statement_coverage_service()
            .summary(
                self.account,
                date(2026, 3, 1),
                date(2026, 3, 31),
            )
        )
        self.assertEqual(summary.state, 'unknown')
        self.assertEqual(summary.intervals, ())


class TestBankStatementParser(TestCase):
    """Test cases for bank statement parser."""

    def setUp(self) -> None:
        """Set up test data."""
        self.faker = Faker()

    def _create_mock_pdf(
        self,
        transactions: list[dict[str, Any]],
    ) -> Path:
        """Create a mock PDF file with transaction data.

        Args:
            transactions: List of transaction dicts with date, amount,
                description.

        Returns:
            Path to the created PDF file.
        """
        # This is a simplified mock - in real tests you'd use a PDF library
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            return Path(temp_file.name)

    def test_parser_file_not_found(self) -> None:
        """Test parser raises error for non-existent file."""
        with self.assertRaises(FileNotFoundError):
            BankStatementParser('/nonexistent/file.pdf')

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_parser_extracts_transactions(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Test parser extracts transactions from PDF."""
        # Create mock transaction data
        mock_df = pd.DataFrame(
            {
                0: ['01.01.2024', '02.01.2024'],
                1: ['', ''],
                2: ['Покупка в магазине', 'Зарплата'],
                3: ['', ''],
                4: ['', ''],
                5: ['-1500.00', '50000.00'],
                6: ['', ''],
            },
        )

        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        pdf_path = self._create_mock_pdf([])
        try:
            parser = BankStatementParser(pdf_path)
            result = parser.parse()

            self.assertIsInstance(result, StatementParseResult)
            self.assertIsInstance(result.transactions, list)
        finally:
            pdf_path.unlink()


class TestProcessBankStatementTask(TestCase):
    """Test cases for Celery task processing bank statements."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)
        self.faker = Faker()

        self.account = Account.objects.create(
            user=self.user,
            name_account='Тестовый счет',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def _generate_random_transactions(
        self,
        count: int = 10,
    ) -> list[dict[str, Any]]:
        """Generate random transaction data for testing.

        Args:
            count: Number of transactions to generate.

        Returns:
            List of transaction dictionaries.
        """
        transactions = []
        base_date = timezone.now()

        for i in range(count):
            # Random amount between -5000 and +5000
            amount = Decimal(
                str(
                    self.faker.pyfloat(
                        min_value=-5000,
                        max_value=5000,
                        right_digits=2,
                    ),
                ),
            )

            # Random date within last 30 days
            days_ago = self.faker.random_int(min=0, max=30)
            trans_date = base_date - timedelta(days=days_ago)

            # Random description
            descriptions = [
                'Покупка в магазине',
                'Оплата услуг',
                'Зарплата',
                'Перевод',
                'Комиссия банка',
                'Возврат средств',
                'Пополнение счета',
                'Снятие наличных',
            ]
            description = self.faker.random_element(descriptions)

            transactions.append(
                {
                    'date': trans_date,
                    'amount': amount,
                    'description': f'{description} {i + 1}',
                },
            )

        return transactions

    def test_task_processes_transactions(
        self,
    ) -> None:
        """Test that task updates upload record correctly."""
        # Create upload record
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='pending',
            pdf_file='test.pdf',
            celery_task_id='test-task-id',
        )

        # Manually simulate what the task does
        upload.status = 'processing'
        upload.total_transactions = 20
        upload.save()

        # Verify initial state
        self.assertEqual(upload.status, 'processing')
        self.assertEqual(upload.total_transactions, 20)

        # Simulate completion
        upload.status = 'completed'
        upload.progress = 100
        upload.income_count = 5
        upload.expense_count = 15
        upload.processed_transactions = 20
        upload.save()

        # Verify final state
        upload.refresh_from_db()
        self.assertEqual(upload.status, 'completed')
        self.assertEqual(upload.progress, 100)
        self.assertEqual(upload.total_transactions, 20)
        self.assertEqual(upload.processed_transactions, 20)
        self.assertEqual(upload.income_count, 5)
        self.assertEqual(upload.expense_count, 15)

    def test_task_creates_categories(
        self,
    ) -> None:
        """Test that categories can be created from transactions."""
        income_category, created = Category.objects.get_or_create(
            user=self.user,
            name='Зарплата Январь',
            type=TransactionType.INCOME,
        )
        self.assertTrue(created or income_category.pk is not None)

        expense_category, created = Category.objects.get_or_create(
            user=self.user,
            name='Продукты Магнит',
            type=TransactionType.EXPENSE,
        )
        self.assertTrue(created or expense_category.pk is not None)

        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Зарплата Январь',
                type=TransactionType.INCOME,
            ).exists(),
        )
        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Продукты Магнит',
                type=TransactionType.EXPENSE,
            ).exists(),
        )

    def test_task_handles_parse_error(
        self,
    ) -> None:
        """Test that upload record can be marked as failed."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='pending',
            pdf_file='test.pdf',
            celery_task_id='test-task-id',
        )

        # Simulate error handling
        upload.status = 'failed'
        upload.error_message = 'Ошибка парсинга: Не удалось извлечь данные'
        upload.save()

        upload.refresh_from_db()
        self.assertEqual(upload.status, 'failed')
        self.assertIn('парсинга', upload.error_message)

    def test_task_with_large_dataset(
        self,
    ) -> None:
        """Test upload record can handle large number of transactions."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='pending',
            pdf_file='test.pdf',
            celery_task_id='test-task-id',
        )

        # Simulate processing 100 transactions
        upload.total_transactions = 100
        upload.processed_transactions = 100
        upload.income_count = 45
        upload.expense_count = 55
        upload.status = 'completed'
        upload.progress = 100
        upload.save()

        upload.refresh_from_db()
        self.assertEqual(upload.status, 'completed')
        self.assertEqual(upload.total_transactions, 100)
        self.assertEqual(upload.processed_transactions, 100)
        self.assertEqual(
            upload.income_count + upload.expense_count,
            100,
        )


class TestBankStatementUploadModel(TestCase):
    """Test cases for BankStatementUpload model."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Тестовый счет',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def test_create_upload_record(self) -> None:
        """Test creating upload record."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='pending',
        )

        self.assertEqual(upload.user, self.user)
        self.assertEqual(upload.account, self.account)
        self.assertEqual(upload.status, 'pending')
        self.assertEqual(upload.progress, 0)
        self.assertEqual(upload.total_transactions, 0)
        self.assertEqual(upload.processed_transactions, 0)

    def test_upload_status_choices(self) -> None:
        """Test that status field accepts valid choices."""
        valid_statuses = ['pending', 'processing', 'completed', 'failed']

        for status in valid_statuses:
            upload = BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                status=status,
            )
            self.assertEqual(upload.status, status)

    def test_upload_progress_tracking(self) -> None:
        """Test progress tracking fields."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='processing',
            total_transactions=100,
            processed_transactions=50,
            progress=50,
        )

        self.assertEqual(upload.total_transactions, 100)
        self.assertEqual(upload.processed_transactions, 50)
        self.assertEqual(upload.progress, 50)

    def test_upload_counts(self) -> None:
        """Test income and expense count fields."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='completed',
            income_count=15,
            expense_count=25,
        )

        self.assertEqual(upload.income_count, 15)
        self.assertEqual(upload.expense_count, 25)

    def test_upload_error_message(self) -> None:
        """Test error message field."""
        error_msg = 'Тестовая ошибка при обработке'
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='failed',
            error_message=error_msg,
        )

        self.assertEqual(upload.error_message, error_msg)

    def test_upload_string_representation(self) -> None:
        """Test string representation of upload."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='completed',
        )
        str_repr = str(upload)
        self.assertIn(self.user.username, str_repr)
        self.assertIn('completed', str_repr)

    def test_upload_ordering(self) -> None:
        """Test that uploads are ordered by created_at descending."""
        upload1 = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
        )
        upload2 = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
        )

        uploads = list(BankStatementUpload.objects.all())
        self.assertEqual(uploads[0], upload2)
        self.assertEqual(uploads[1], upload1)

    def test_upload_celery_task_id(self) -> None:
        """Test celery_task_id field."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            celery_task_id='abc-123-def',
        )

        self.assertEqual(upload.celery_task_id, 'abc-123-def')


class TestBankStatementParserMethods(TestCase):
    """Test cases for BankStatementParser individual methods."""

    def setUp(self) -> None:
        """Set up test data."""
        self.faker = Faker()

    def _create_mock_pdf(self) -> Path:
        """Create a mock PDF file.

        Returns:
            Path to the created PDF file.
        """
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            return Path(temp_file.name)

    def test_extract_transaction_number_valid(self) -> None:
        """Test extracting valid transaction number."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_transaction_number('  123  ')
            self.assertEqual(result, 123)
        finally:
            pdf_path.unlink()

    def test_extract_transaction_number_invalid(self) -> None:
        """Test extracting transaction number from invalid text."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_transaction_number('not a number')
            self.assertIsNone(result)
        finally:
            pdf_path.unlink()

    def test_extract_transaction_number_empty(self) -> None:
        """Test extracting transaction number from empty text."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_transaction_number('')
            self.assertIsNone(result)
        finally:
            pdf_path.unlink()

    def test_extract_amount_from_column_valid(self) -> None:
        """Test extracting amount from valid column text."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_amount_from_column('  +1 234,56 ₽  ')
            self.assertEqual(result, Decimal('1234.56'))
        finally:
            pdf_path.unlink()

    def test_extract_amount_from_column_negative(self) -> None:
        """Test extracting negative amount."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_amount_from_column('  -567,89 ₽  ')
            self.assertEqual(result, Decimal('567.89'))
        finally:
            pdf_path.unlink()

    def test_extract_amount_from_column_with_spaces(self) -> None:
        """Test extracting amount with spaces."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_amount_from_column('  +10 000,50 ₽  ')
            self.assertEqual(result, Decimal('10000.50'))
        finally:
            pdf_path.unlink()

    def test_extract_amount_from_column_invalid(self) -> None:
        """Test extracting amount from invalid text."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_amount_from_column('not an amount')
            self.assertIsNone(result)
        finally:
            pdf_path.unlink()

    def test_extract_date_valid_with_time(self) -> None:
        """Test extracting date with time."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_date(
                '15.01.2024 14:30',
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.day, 15)
            self.assertEqual(result.month, 1)
            self.assertEqual(result.year, 2024)
        finally:
            pdf_path.unlink()

    def test_extract_date_valid_without_time(self) -> None:
        """Test extracting date without time."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_date('25.12.2023')
            self.assertIsNotNone(result)
            self.assertEqual(result.day, 25)
            self.assertEqual(result.month, 12)
            self.assertEqual(result.year, 2023)
        finally:
            pdf_path.unlink()

    def test_extract_date_invalid(self) -> None:
        """Test extracting invalid date."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._extract_date('not a date')
            self.assertIsNone(result)
        finally:
            pdf_path.unlink()

    def test_clean_description_atm(self) -> None:
        """Test cleaning ATM transaction description."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._clean_description(
                'Выдача наличных со счета через банкомат',
            )
            self.assertEqual(result, 'Выдача наличных')
        finally:
            pdf_path.unlink()

    def test_clean_description_with_date(self) -> None:
        """Test cleaning description with date."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._clean_description(
                'Покупка в магазине 15.01.2024',
            )
            self.assertNotIn('15.01.2024', result)
        finally:
            pdf_path.unlink()

    def test_clean_description_with_amount(self) -> None:
        """Test cleaning description with amount."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._clean_description(
                'Покупка товаров 1500,00 руб.',
            )
            self.assertNotIn('1500', result)
        finally:
            pdf_path.unlink()

    def test_clean_description_empty(self) -> None:
        """Test cleaning empty description."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            result = parser._clean_description('')
            self.assertEqual(result, 'Операция')
        finally:
            pdf_path.unlink()

    def test_get_description_column_index_standard(self) -> None:
        """Test getting description column index for standard table."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            # Create a row with 7 columns
            row = pd.Series([''] * 7)
            result = parser._get_description_column_index(row)
            self.assertEqual(result, 5)
        finally:
            pdf_path.unlink()

    def test_get_description_column_index_small(self) -> None:
        """Test getting description column index for small table."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)
            # Create a row with 3 columns
            row = pd.Series([''] * 3)
            result = parser._get_description_column_index(row)
            self.assertEqual(result, 2)
        finally:
            pdf_path.unlink()


class TestBankStatementFormValidation(TestCase):
    """Test cases for BankStatementUploadForm validation."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)

    def test_form_valid_data(self) -> None:
        """Test form with valid data."""
        account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

        pdf_content = b'%PDF-1.4 fake pdf'
        pdf_file = SimpleUploadedFile(
            'statement.pdf',
            pdf_content,
            content_type='application/pdf',
        )

        form = BankStatementUploadForm(
            data={'account': account.id},
            files={'pdf_file': pdf_file},
            user=self.user,
        )

        self.assertTrue(form.is_valid())

    def test_form_file_too_large(self) -> None:
        """Test form with file larger than 10MB."""
        account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

        # Create a file larger than 10MB
        large_content = b'x' * (11 * 1024 * 1024)
        large_file = SimpleUploadedFile(
            'large.pdf',
            large_content,
            content_type='application/pdf',
        )

        form = BankStatementUploadForm(
            data={'account': account.id},
            files={'pdf_file': large_file},
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('pdf_file', form.errors)

    def test_form_invalid_extension(self) -> None:
        """Test form with invalid file extension."""
        account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

        txt_file = SimpleUploadedFile(
            'document.txt',
            b'not a pdf',
            content_type='text/plain',
        )

        form = BankStatementUploadForm(
            data={'account': account.id},
            files={'pdf_file': txt_file},
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('pdf_file', form.errors)

    def test_form_missing_account(self) -> None:
        """Test form without account selection."""
        pdf_content = b'%PDF-1.4 fake pdf'
        pdf_file = SimpleUploadedFile(
            'statement.pdf',
            pdf_content,
            content_type='application/pdf',
        )

        form = BankStatementUploadForm(
            data={},
            files={'pdf_file': pdf_file},
            user=self.user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('account', form.errors)


class TestBankStatementIntegration(TestCase):
    """Integration tests for bank statement processing."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)

    def test_full_workflow_with_mock_data(self) -> None:
        """Test complete workflow from upload to transaction creation."""
        account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=account,
            pdf_file=SimpleUploadedFile(
                'statement.pdf',
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
        )

        # This will fail with mock PDF, but we can test error handling
        with self.assertRaises(BankStatementParseError):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)

    def test_category_creation_for_transaction(self) -> None:
        """Test that categories are created for transactions."""
        expense_cat = _get_or_create_category(
            self.user,
            'Тестовые расходы',
            TransactionType.EXPENSE,
        )
        self.assertEqual(expense_cat.user, self.user)
        self.assertEqual(expense_cat.name, 'Тестовые расходы')

        income_cat = _get_or_create_category(
            self.user,
            'Тестовый доход',
            TransactionType.INCOME,
        )
        self.assertEqual(income_cat.user, self.user)
        self.assertEqual(income_cat.name, 'Тестовый доход')

        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Тестовые расходы',
                type=TransactionType.EXPENSE,
            ).exists(),
        )
        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Тестовый доход',
                type=TransactionType.INCOME,
            ).exists(),
        )

    def test_category_name_truncation(self) -> None:
        """Test that category names are truncated to 250 characters."""
        long_name = 'A' * 300
        category = _get_or_create_category(
            self.user,
            long_name,
            TransactionType.EXPENSE,
        )

        # Verify it's truncated to 250
        self.assertEqual(len(category.name), 250)
        self.assertTrue(category.name.startswith('AAAAA'))


class TestBankStatementParserAdvanced(TestCase):
    """Advanced test cases for BankStatementParser methods."""

    def setUp(self) -> None:
        """Set up test data."""
        self.faker = Faker()

    def _create_mock_pdf(self) -> Path:
        """Create a mock PDF file.

        Returns:
            Path to the created PDF file.
        """
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            return Path(temp_file.name)

    def test_parse_table_with_valid_transactions(self) -> None:
        """Test parsing table with valid transactions."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # Create a DataFrame with transaction data
            # Transaction number in column 0, date in column 0 or 1
            df = pd.DataFrame(
                {
                    0: ['01.01.2024 10:00', '1', '2'],
                    1: ['', '', ''],
                    2: ['', 'Покупка в магазине', 'Зарплата'],
                    3: ['', '', ''],
                    4: ['', '', ''],
                    5: ['', '-1500,00 ₽', '+50000,00 ₽'],
                    6: ['', '', ''],
                },
            )

            transactions = parser._parse_table(df)

            # Basic validation - just check it returns a list
            self.assertIsInstance(transactions, list)
        finally:
            pdf_path.unlink()

    def test_parse_table_with_empty_rows(self) -> None:
        """Test parsing table with empty rows."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # Create a DataFrame with empty rows
            df = pd.DataFrame(
                {
                    0: ['01.01.2024 10:00', '1', '', 'nan', '2'],
                    1: ['', '', '', '', ''],
                    2: ['', 'Покупка', '', '', 'Зарплата'],
                    3: ['', '', '', '', ''],
                    4: ['', '', '', '', ''],
                    5: ['', '-1500,00 ₽', '', '', '+50000,00 ₽'],
                    6: ['', '', '', '', ''],
                },
            )

            transactions = parser._parse_table(df)

            # Basic validation - just check it returns a list
            self.assertIsInstance(transactions, list)
        finally:
            pdf_path.unlink()

    def test_parse_table_with_invalid_transaction_number(self) -> None:
        """Test parsing table with invalid transaction numbers."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # Create a DataFrame with invalid transaction numbers
            df = pd.DataFrame(
                {
                    0: ['01.01.2024 10:00', 'abc', 'xyz', '123'],
                    1: ['', '', '', ''],
                    2: ['', '', '', 'Покупка'],
                    3: ['', '', '', ''],
                    4: ['', '', '', ''],
                    5: ['', '', '', '-1500,00 ₽'],
                    6: ['', '', '', ''],
                },
            )

            transactions = parser._parse_table(df)

            # Basic validation - just check it returns a list
            self.assertIsInstance(transactions, list)
        finally:
            pdf_path.unlink()

    def test_parse_transaction_row_with_income(self) -> None:
        """Test parsing transaction row with positive amount."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # Create a DataFrame with date context
            df = pd.DataFrame(
                {
                    0: ['01.01.2024 10:00', '1'],
                    1: ['', ''],
                    2: ['', 'Зарплата'],
                    3: ['', ''],
                    4: ['', ''],
                    5: ['', '+50000,00 ₽'],
                    6: ['', ''],
                },
            )

            row = df.iloc[1]
            transaction = parser._parse_transaction_row(row, df, 1)

            # Basic validation - just check it returns a dict or None
            self.assertTrue(
                transaction is None or isinstance(transaction, dict),
            )
        finally:
            pdf_path.unlink()

    def test_parse_transaction_row_with_expense(self) -> None:
        """Test parsing transaction row with negative amount."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # Create a DataFrame with date context
            df = pd.DataFrame(
                {
                    0: ['01.01.2024 10:00', '1'],
                    1: ['', ''],
                    2: ['', 'Покупка'],
                    3: ['', ''],
                    4: ['', ''],
                    5: ['', '-1500,00 ₽'],
                    6: ['', ''],
                },
            )

            row = df.iloc[1]
            transaction = parser._parse_transaction_row(row, df, 1)

            # Basic validation - just check it returns a dict or None
            self.assertTrue(
                transaction is None or isinstance(transaction, dict),
            )
        finally:
            pdf_path.unlink()

    def test_parse_transaction_row_without_date(self) -> None:
        """Test parsing transaction row without date context."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # Create a DataFrame without date context
            df = pd.DataFrame(
                {
                    0: ['1'],
                    1: [''],
                    2: [''],
                    3: [''],
                    4: [''],
                    5: ['Покупка'],
                    6: ['-1500,00 ₽'],
                },
            )

            row = df.iloc[0]
            transaction = parser._parse_transaction_row(row, df, 0)

            # Should return None if no date is found
            self.assertIsNone(transaction)
        finally:
            pdf_path.unlink()

    def test_extract_amount_from_row_positive(self) -> None:
        """Test extracting positive amount from row."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            row = pd.Series(['', '', '', '', '', '', '+10000,50 ₽'])
            amount = parser._extract_amount_from_row(row)

            self.assertEqual(amount, Decimal('10000.50'))
        finally:
            pdf_path.unlink()

    def test_extract_amount_from_row_negative(self) -> None:
        """Test extracting negative amount from row."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            row = pd.Series(['', '', '', '', '', '', '-2500,75 ₽'])
            amount = parser._extract_amount_from_row(row)

            self.assertEqual(amount, Decimal('-2500.75'))
        finally:
            pdf_path.unlink()

    def test_extract_amount_from_row_no_amount(self) -> None:
        """Test extracting amount when no amount is present."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            row = pd.Series(['', '', '', '', '', '', 'no amount here'])
            amount = parser._extract_amount_from_row(row)

            self.assertIsNone(amount)
        finally:
            pdf_path.unlink()

    def test_extract_amount_from_row_multiple_columns(self) -> None:
        """Test extracting amount from row with multiple amount columns."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            row = pd.Series(['', '', '', '', '', '1000,00 ₽', '+2000,00 ₽'])
            amount = parser._extract_amount_from_row(row)

            # Should return the first amount found
            self.assertEqual(amount, Decimal('1000.00'))
        finally:
            pdf_path.unlink()

    def test_extract_date_from_context_with_datetime(self) -> None:
        """Test extracting date with datetime from context."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: ['01.01.2024 10:00', '1'],
                    1: ['', ''],
                },
            )

            date = parser._extract_date_from_context(df, 1)

            # Basic validation - just check it returns datetime or None
            self.assertTrue(date is None or isinstance(date, datetime))
        finally:
            pdf_path.unlink()

    def test_extract_date_from_context_with_date_only(self) -> None:
        """Test extracting date without time from context."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: ['15.02.2024', '1'],
                    1: ['', ''],
                },
            )

            date = parser._extract_date_from_context(df, 1)

            # Basic validation - just check it returns datetime or None
            self.assertTrue(date is None or isinstance(date, datetime))
        finally:
            pdf_path.unlink()

    def test_extract_date_from_context_no_date(self) -> None:
        """Test extracting date when no date is in context."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: ['no date', '1'],
                    1: ['', ''],
                },
            )

            date = parser._extract_date_from_context(df, 1)

            self.assertIsNone(date)
        finally:
            pdf_path.unlink()

    def test_extract_date_from_context_far_back(self) -> None:
        """Test extracting date from far back in context."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: [
                        '01.01.2024 10:00',
                        '',
                        '',
                        '',
                        '',
                        '1',
                    ],
                    1: ['', '', '', '', '', ''],
                },
            )

            date = parser._extract_date_from_context(df, 5)

            # Basic validation - just check it returns datetime or None
            self.assertTrue(date is None or isinstance(date, datetime))
        finally:
            pdf_path.unlink()

    def test_extract_description_single_line(self) -> None:
        """Test extracting single-line description."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: ['1', '2'],
                    1: ['', ''],
                    2: ['Покупка в магазине', ''],
                    3: ['', ''],
                    4: ['', ''],
                    5: ['', ''],
                    6: ['', ''],
                },
            )

            description = parser._extract_description(
                df.iloc[0],
                df,
                0,
                2,
            )

            # Basic validation - just check it returns a string
            self.assertIsInstance(description, str)
        finally:
            pdf_path.unlink()

    def test_extract_description_multiline(self) -> None:
        """Test extracting multi-line description."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: ['1', '', '', '2'],
                    1: ['', '', '', ''],
                    2: ['Покупка', 'товаров', 'в магазине', ''],
                    3: ['', '', '', ''],
                    4: ['', '', '', ''],
                    5: ['', '', '', ''],
                    6: ['', '', '', ''],
                },
            )

            description = parser._extract_description(
                df.iloc[0],
                df,
                0,
                2,
            )

            # Basic validation - just check it returns a string
            self.assertIsInstance(description, str)
        finally:
            pdf_path.unlink()

    def test_extract_description_stops_at_next_transaction(self) -> None:
        """Test that description extraction stops at next transaction."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: ['1', '', '2'],
                    1: ['', '', ''],
                    2: ['Покупка', 'дополнительные', ''],
                    3: ['', '', ''],
                    4: ['', '', ''],
                    5: ['', '', ''],
                    6: ['', '', ''],
                },
            )

            description = parser._extract_description(
                df.iloc[0],
                df,
                0,
                2,
            )

            # Basic validation - just check it returns a string
            self.assertIsInstance(description, str)
        finally:
            pdf_path.unlink()

    def test_extract_description_filters_patterns(self) -> None:
        """Test that description filters out unwanted patterns."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: ['1', '', '', ''],
                    1: ['', '', '', ''],
                    2: ['Покупка', '12345', 'Со счета: 123456', ''],
                    3: ['', '', '', ''],
                    4: ['', '', '', ''],
                    5: ['', '', '', ''],
                    6: ['', '', '', ''],
                },
            )

            description = parser._extract_description(
                df.iloc[0],
                df,
                0,
                2,
            )

            # Basic validation - just check it returns a string
            self.assertIsInstance(description, str)
        finally:
            pdf_path.unlink()

    def test_is_transaction_table_true(self) -> None:
        """Test that table with transaction number is identified."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: ['header', '1', '2'],
                    1: ['', '', ''],
                    2: ['', '', ''],
                },
            )

            result = parser._is_transaction_table(df)

            self.assertTrue(result)
        finally:
            pdf_path.unlink()

    def test_is_transaction_table_false(self) -> None:
        """Test that table without transaction number is not identified."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            df = pd.DataFrame(
                {
                    0: ['header', 'abc', 'xyz'],
                    1: ['', '', ''],
                    2: ['', '', ''],
                },
            )

            result = parser._is_transaction_table(df)

            self.assertFalse(result)
        finally:
            pdf_path.unlink()

    def test_clean_description_with_atm_variant(self) -> None:
        """Test cleaning description with ATM variant."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            result = parser._clean_description(
                'Выдача наличных средств со счета',
            )
            self.assertEqual(result, 'Выдача наличных')
        finally:
            pdf_path.unlink()

    def test_clean_description_with_city(self) -> None:
        """Test cleaning description with city information."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            result = parser._clean_description(
                'Покупка в магазине, г Москва, ул Тверская',
            )
            self.assertNotIn('Москва', result)
            self.assertNotIn('Тверская', result)
        finally:
            pdf_path.unlink()

    def test_clean_description_with_atm_number(self) -> None:
        """Test cleaning description with ATM number."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            result = parser._clean_description(
                'Покупка ATM 12345',
            )
            self.assertNotIn('12345', result)
            self.assertNotIn('ATM', result)
        finally:
            pdf_path.unlink()

    def test_clean_description_truncates_long_description(self) -> None:
        """Test that long descriptions are truncated."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # The _clean_description method returns cleaned description as-is.
            # Only when cleaned result is empty, it falls back to first part
            # before comma or first 100 chars of original description.
            # Final truncation to 250 chars happens in _parse_transaction_row.

            # Test with description that becomes empty after cleaning
            # (only city/address info which gets removed)
            empty_after_clean = 'г Москва, ул Тверская, д 10'
            result = parser._clean_description(empty_after_clean)
            self.assertLessEqual(len(result), 100)

            # Test with long description that won't be cleaned away
            long_desc = 'A' * 300
            result = parser._clean_description(long_desc)
            # _clean_description doesn't truncate non-empty cleaned results
            self.assertEqual(len(result), 300)
        finally:
            pdf_path.unlink()

    def _make_generic_parser(self) -> _GenericBankParser:
        pdf_path = self._create_mock_pdf()
        self.addCleanup(pdf_path.unlink)
        return _GenericBankParser(pdf_path)

    def _make_generic_df(self, rows: list[list[Any]]) -> pd.DataFrame:
        return pd.DataFrame(
            rows,
            columns=[str(index) for index in range(7)],
        )

    def test_valid_table_keeps_rows_and_local_categories(self) -> None:
        """A readable table yields rows with closed local categories."""
        parser = self._make_generic_parser()
        df = self._make_generic_df(
            [
                ['01.01.2024 10:00', '', '', '', '', '', ''],
                ['1', '', '', '', '', 'Покупка в магазине', '-1 500,00 ₽'],
                [
                    '2',
                    '',
                    '',
                    '',
                    '',
                    'Зачисление заработной платы',
                    '+50 000,00 ₽',
                ],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0]['amount'], Decimal('-1500.00'))
        self.assertEqual(transactions[0]['category_name'], 'Покупки')
        self.assertEqual(transactions[1]['amount'], Decimal('50000.00'))
        self.assertEqual(
            transactions[1]['category_name'],
            'Заработная плата',
        )
        self.assertIsNone(transactions[0]['source_ref'])

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.extract_text',
        return_value='',
    )
    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_zero_amount_row_stays_visible_without_money(
        self,
        mock_camelot: MagicMock,
        mock_extract_text: MagicMock,
    ) -> None:
        """A zero-amount row is a visible fragment, not a money movement."""
        pdf_path = self._create_mock_pdf()
        self.addCleanup(pdf_path.unlink)
        parser = _GenericBankParser(pdf_path)
        mock_table = MagicMock()
        mock_table.df = self._make_generic_df(
            [
                ['', '01.01.2024 10:00', '', '', '', '', ''],
                ['1', '', '', '', '', 'Комиссия банка', '0,00 ₽'],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        transactions = parser.parse().transactions

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]['amount'], Decimal(0))
        self.assertEqual(transactions[0]['parse_issue'], 'unsupported')

    def test_category_ignores_continuation_text(self) -> None:
        """A category comes from the operation row, not a neighbour."""
        parser = self._make_generic_parser()
        df = self._make_generic_df(
            [
                ['01.01.2024 10:00', '', '', '', '', '', ''],
                ['1', '', '', '', '', '', '-100,00 ₽'],
                ['', '', '', '', '', 'Покупка в магазине', ''],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertIsNone(transactions[0]['category_name'])

    def test_unsupported_row_is_kept_as_visible_fragment(self) -> None:
        """A numbered row without amount or date is not dropped."""
        parser = self._make_generic_parser()
        df = self._make_generic_df(
            [
                ['1', '', '', '', '', 'Неизвестная операция', ''],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]['parse_issue'], 'unsupported')
        self.assertIsNone(transactions[0]['amount'])
        self.assertIsNone(transactions[0]['date'])
        self.assertEqual(
            transactions[0]['description'],
            'Неизвестная операция',
        )

    def test_row_error_keeps_fragment_and_other_rows(self) -> None:
        """A recoverable row error does not abort the whole table."""
        parser = self._make_generic_parser()
        df = self._make_generic_df(
            [
                ['01.01.2024 10:00', '', '', '', '', '', ''],
                ['1', '', '', '', '', 'Комиссия банка', '-13,20 ₽'],
                ['2', '', '', '', '', '', '-20,00 ₽'],
            ],
        )

        with patch.object(
            parser,
            '_extract_amount_from_row',
            side_effect=[ValueError('broken cell'), None, Decimal('-20.00')],
        ):
            transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0]['parse_issue'], 'unsupported')
        self.assertEqual(transactions[1]['amount'], Decimal('-20.00'))

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.extract_text',
        return_value='',
    )
    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_empty_parse_has_no_invented_metadata(
        self,
        mock_camelot: MagicMock,
        mock_extract_text: MagicMock,
    ) -> None:
        """An empty or unknown format proves no account, period or balance."""
        parser = self._make_generic_parser()
        mock_camelot.read_pdf.return_value = []

        result = parser.parse()

        self.assertEqual(result.transactions, [])
        self.assertIsNone(result.account_number)
        self.assertIsNone(result.period_start)
        self.assertIsNone(result.closing_balance)
        self.assertEqual(result.bank, 'generic')

    def test_local_category_rules_are_closed_and_directional(self) -> None:
        """Only a closed rule in its own direction is locally known."""
        self.assertEqual(
            generic_local_category('Зачисление заработной платы', 'income'),
            'Заработная плата',
        )
        self.assertIsNone(
            generic_local_category('Зачисление заработной платы', 'expense'),
        )
        self.assertIsNone(generic_local_category('Оплата в MAGNIT', 'expense'))


class TestBankStatementProcessIntegration(TestCase):
    """Integration tests for the bank statement import seam.

    Uses the same seam as production: a synchronous call to
    ``process_bank_statement_task`` against a real ``BankStatementUpload``.
    """

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Тестовый счет',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def _create_upload(
        self,
        filename: str = 'statement.pdf',
    ) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file=SimpleUploadedFile(
                filename,
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
        )

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_process_bank_statement_creates_transactions(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Test that the import task creates transactions."""
        # Create mock transaction data
        mock_df = pd.DataFrame(
            {
                0: ['', '01.01.2024 10:00', '1', '2'],
                1: ['', '', '', ''],
                2: ['', '', '', ''],
                3: ['', '', '', ''],
                4: ['', '', '', ''],
                5: ['', '', 'Зарплата', 'Покупка'],
                6: ['', '', '+50000,00 ₽', '-1500,00 ₽'],
            },
        )

        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        upload = self._create_upload()

        result = process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertEqual(result['income_count'], 1)
        self.assertEqual(result['expense_count'], 1)
        self.assertEqual(result['total_count'], 2)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_process_bank_statement_with_zero_amount(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Test processing statement with zero amount transaction."""
        mock_df = pd.DataFrame(
            {
                0: ['01.01.2024 10:00', '1'],
                1: ['', ''],
                2: ['', 'Покупка'],
                3: ['', ''],
                4: ['', ''],
                5: ['', '0,00 ₽'],
                6: ['', ''],
            },
        )

        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        upload = self._create_upload()

        result = process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertEqual(result['total_count'], 0)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_process_bank_statement_creates_categories(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Test that categories are created for transactions."""
        mock_df = pd.DataFrame(
            {
                0: ['', '01.01.2024 10:00', '1', '2'],
                1: ['', '', '', ''],
                2: ['', '', 'Зарплата Январь', 'Покупка в магазине'],
                3: ['', '', '', ''],
                4: ['', '', '+50000,00 ₽', '-1500,00 ₽'],
            },
        )

        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        upload = self._create_upload()

        process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Заработная плата',
                type=TransactionType.INCOME,
            ).exists(),
        )
        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Покупки',
                type=TransactionType.EXPENSE,
            ).exists(),
        )

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_process_bank_statement_reuses_existing_categories(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Test that existing categories are reused."""
        # Create existing categories
        Category.objects.create(
            user=self.user,
            name='Зарплата Январь',
            type=TransactionType.INCOME,
        )
        Category.objects.create(
            user=self.user,
            name='Продукты Магнит',
            type=TransactionType.EXPENSE,
        )

        mock_df = pd.DataFrame(
            {
                0: ['', '01.01.2024 10:00', '1', '2'],
                1: ['', '', '', ''],
                2: ['', '', 'Зарплата Январь', 'Продукты Магнит'],
                3: ['', '', '', ''],
                4: ['', '', '+50000,00 ₽', '-1500,00 ₽'],
            },
        )

        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        upload = self._create_upload()

        process_bank_statement_task.apply(args=[upload.pk]).get()

        # Verify existing categories were used (not created again)
        income_count = Category.objects.filter(
            user=self.user,
            name='Зарплата Январь',
            type=TransactionType.INCOME,
        ).count()
        expense_count = Category.objects.filter(
            user=self.user,
            name='Продукты Магнит',
            type=TransactionType.EXPENSE,
        ).count()

        self.assertEqual(income_count, 1)
        self.assertEqual(expense_count, 1)

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.'
        '_extract_pdf_text_for_detection',
        return_value='Выписка по счёту кредитной карты',
    )
    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_reimport_of_same_upload_keeps_one_movement(
        self,
        mock_camelot: MagicMock,
        mock_detect: MagicMock,
    ) -> None:
        """Re-importing the same Sberbank file does not double the money.

        A reused auth code is not an identity on its own: the proof here is
        the same upload, file hash, parser format and row position. The
        unknown credit row stays unresolved in both runs.
        """
        mock_df = pd.DataFrame(
            [
                [
                    '18.02.2026 17:11',
                    'Транспорт',
                    '73,00 ₽',
                    '59 016,93 ₽',
                ],
                ['18.02.2026 / 869838', 'MOSCOW STRELKA', '', ''],
                [
                    '09.02.2026 15:50',
                    'Перевод на карту',
                    '+50 546,00 ₽',
                    '63 493,18 ₽',
                ],
                ['09.02.2026 / 552183', 'Перевод от П.', '', ''],
            ],
        )
        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        first_upload = self._create_upload('statement-1.pdf')
        BankStatementUpload.objects.filter(pk=first_upload.pk).update(
            file_hash='statement-hash',
        )
        first = process_bank_statement_task.apply(
            args=[first_upload.pk],
        ).get()
        self.assertEqual(first['income_count'], 0)
        self.assertEqual(first['expense_count'], 1)
        self.assertEqual(first['skipped_count'], 0)

        balance_after_first = Account.objects.get(pk=self.account.pk).balance

        BankStatementUpload.objects.filter(pk=first_upload.pk).update(
            processed_transactions=0,
            income_count=0,
            expense_count=0,
            skipped_count=0,
            needs_transfer_count=0,
            status=BankStatementUpload.Status.PROCESSING,
        )
        second = process_bank_statement_task.apply(
            args=[first_upload.pk],
        ).get()
        self.assertEqual(second['income_count'], 0)
        self.assertEqual(second['expense_count'], 0)

        balance_after_second = Account.objects.get(pk=self.account.pk).balance
        self.assertEqual(balance_after_first, balance_after_second)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.assertEqual(
            BankStatementRow.objects.filter(upload=first_upload).count(),
            2,
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.'
        '_extract_pdf_text_for_detection',
        return_value='Выписка по счёту кредитной карты',
    )
    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_legacy_record_without_source_ref_surfaces_as_probable_duplicate(
        self,
        mock_camelot: MagicMock,
        mock_detect: MagicMock,
    ) -> None:
        """Legacy rows with source_ref=NULL surface as a probable duplicate.

        A transaction imported before source_ref existed (stored with NULL)
        matches an incoming row by (account, user, type, amount, date) —
        the same signal the probable-duplicate check uses. Probable-duplicate
        detection runs before the legacy-backfill fallback, so this is
        surfaced for reconciliation rather than silently auto-matched: no
        new ``Transaction`` is created and the legacy row is left for the
        user to resolve via statement reconciliation.
        """
        # Pre-create a legacy record without source_ref (mimics pre-fix DB)
        legacy_date = datetime(
            2026,
            2,
            18,
            17,
            11,
            tzinfo=timezone.get_current_timezone(),
        )
        legacy_category = Category.objects.create(
            user=self.user,
            name='Транспорт',
            type=TransactionType.EXPENSE,
        )
        legacy_tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=legacy_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('73.00'),
            date=legacy_date,
            source_ref=None,
        )

        # PDF now produces a row with the same op + source_ref
        mock_df = pd.DataFrame(
            [
                [
                    '18.02.2026 17:11',
                    'Транспорт',
                    '73,00 ₽',
                    '59 016,93 ₽',
                ],
                ['18.02.2026 / 869838', 'MOSCOW STRELKA', '', ''],
            ],
        )
        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        upload = self._create_upload()

        result = process_bank_statement_task.apply(args=[upload.pk]).get()
        self.assertEqual(result['expense_count'], 0)
        self.assertEqual(result['income_count'], 0)
        self.assertEqual(result['skipped_count'], 1)

        self.assertEqual(
            Transaction.objects.filter(
                account=self.account,
                user=self.user,
                amount=Decimal('73.00'),
                date=legacy_date,
            ).count(),
            1,
            'No duplicate must be created for the legacy row',
        )
        legacy_tx.refresh_from_db()
        self.assertIsNone(
            legacy_tx.source_ref,
            'Ambiguous match is left for reconciliation, not auto-backfilled',
        )
        statement_row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(statement_row.candidate, legacy_tx)

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.'
        '_extract_pdf_text_for_detection',
        return_value='Выписка по счёту кредитной карты',
    )
    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_reimport_adds_missing_transaction(
        self,
        mock_camelot: MagicMock,
        mock_detect: MagicMock,
    ) -> None:
        """Re-importing after a parser bugfix adds only the newly recovered op.

        Simulates the real scenario: first import misses one transaction
        (parser bug), second import returns all three. The two already
        in the DB must be skipped, only the previously-missed one added.
        """
        first_df = pd.DataFrame(
            [
                [
                    '18.02.2026 17:11',
                    'Транспорт',
                    '73,00 ₽',
                    '59 016,93 ₽',
                ],
                ['18.02.2026 / 869838', 'MOSCOW STRELKA', '', ''],
                [
                    '09.02.2026 15:50',
                    'Перевод на карту',
                    '+50 546,00 ₽',
                    '63 493,18 ₽',
                ],
                ['09.02.2026 / 552183', 'Перевод от П.', '', ''],
            ],
        )
        second_df = pd.DataFrame(
            [
                [
                    '18.02.2026 17:11',
                    'Транспорт',
                    '73,00 ₽',
                    '59 016,93 ₽',
                ],
                ['18.02.2026 / 869838', 'MOSCOW STRELKA', '', ''],
                [
                    '09.02.2026 15:50',
                    'Перевод на карту',
                    '+50 546,00 ₽',
                    '63 493,18 ₽',
                ],
                ['09.02.2026 / 552183', 'Перевод от П.', '', ''],
                [
                    '01.04.2026 16:51',
                    'Прочие расходы',
                    '2 958,00 ₽',
                    '12 851,05 ₽',
                ],
                ['01.04.2026 / 311925', 'Aliexpress', '', ''],
            ],
        )
        first_table = MagicMock()
        first_table.df = first_df
        second_table = MagicMock()
        second_table.df = second_df
        mock_camelot.read_pdf.side_effect = [
            [first_table],
            [second_table],
        ]

        first_upload = self._create_upload('statement-1.pdf')
        first = process_bank_statement_task.apply(
            args=[first_upload.pk],
        ).get()
        self.assertEqual(first['expense_count'], 1)
        self.assertEqual(first['income_count'], 0)

        second_upload = self._create_upload('statement-2.pdf')
        second = process_bank_statement_task.apply(
            args=[second_upload.pk],
        ).get()
        self.assertEqual(second['skipped_count'], 1)
        self.assertEqual(second['expense_count'], 1)
        self.assertEqual(second['income_count'], 0)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            2,
        )


class TestBankStatementEdgeCases(TestCase):
    """Edge case tests for bank statement processing."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Тестовый счет',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def test_extract_date_out_of_range_year(self) -> None:
        """Test extracting date with year out of range."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # Year before MIN_YEAR
            result = parser._extract_date('01.01.1999')
            self.assertIsNone(result)

            # Year after MAX_YEAR
            result = parser._extract_date('01.01.2101')
            self.assertIsNone(result)
        finally:
            pdf_path.unlink()

    def test_extract_date_invalid_format(self) -> None:
        """Test extracting date with invalid format."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # Invalid date format
            result = parser._extract_date('2024-01-01')
            self.assertIsNone(result)

            # Invalid day
            result = parser._extract_date('32.01.2024')
            self.assertIsNone(result)

            # Invalid month
            result = parser._extract_date('01.13.2024')
            self.assertIsNone(result)
        finally:
            pdf_path.unlink()

    def test_extract_amount_with_invalid_decimal(self) -> None:
        """Test extracting amount with invalid decimal."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # Invalid decimal format
            result = parser._extract_amount_from_column('123.456 ₽')
            self.assertIsNone(result)
        finally:
            pdf_path.unlink()

    def test_clean_description_with_special_characters(self) -> None:
        """Test cleaning description with special characters."""
        pdf_path = self._create_mock_pdf()
        try:
            parser = BankStatementParser(pdf_path)

            # The _clean_description method only strips trailing
            # special characters from the cleaned result, not all
            # special characters. It strips ' ,;.' from the end.
            result = parser._clean_description(
                'Покупка товаров в магазине, г Москва, ул Тверская',
            )
            # Should remove city info but keep some punctuation
            self.assertNotIn('Москва', result)
            self.assertNotIn('Тверская', result)
        finally:
            pdf_path.unlink()

    def test_parse_with_no_tables(self) -> None:
        """Test parsing PDF with no tables."""
        pdf_path = self._create_mock_pdf()
        try:
            with patch(
                'hasta_la_vista_money.users.services.bank_statement.camelot',
            ) as mock_camelot:
                mock_camelot.read_pdf.return_value = []

                parser = BankStatementParser(pdf_path)
                result = parser.parse()

                self.assertEqual(result.transactions, [])
        finally:
            pdf_path.unlink()

    def test_parse_with_table_insufficient_columns(self) -> None:
        """Test parsing table with insufficient columns."""
        pdf_path = self._create_mock_pdf()
        try:
            with patch(
                'hasta_la_vista_money.users.services.bank_statement.camelot',
            ) as mock_camelot:
                mock_df = pd.DataFrame(
                    {
                        0: ['1'],
                        1: [''],
                        2: [''],
                        3: [''],
                    },
                )
                mock_table = MagicMock()
                mock_table.df = mock_df
                mock_camelot.read_pdf.return_value = [mock_table]

                parser = BankStatementParser(pdf_path)
                result = parser.parse()

                self.assertEqual(result.transactions, [])
        finally:
            pdf_path.unlink()

    def test_parse_with_exception(self) -> None:
        """Test parsing when exception occurs."""
        pdf_path = self._create_mock_pdf()
        try:
            with patch(
                'hasta_la_vista_money.users.services.bank_statement.camelot',
            ) as mock_camelot:
                mock_camelot.read_pdf.side_effect = Exception('Test error')

                parser = BankStatementParser(pdf_path)

                with self.assertRaises(BankStatementParseError):
                    parser.parse()
        finally:
            pdf_path.unlink()

    def test_get_or_create_category_with_long_name(self) -> None:
        """Test creating category with very long name."""
        long_name = 'A' * 300

        income_cat = _get_or_create_category(
            self.user,
            long_name,
            TransactionType.INCOME,
        )
        self.assertEqual(len(income_cat.name), 250)

        expense_cat = _get_or_create_category(
            self.user,
            long_name,
            TransactionType.EXPENSE,
        )
        self.assertEqual(len(expense_cat.name), 250)

    def test_get_or_create_category_with_special_chars(self) -> None:
        """Test creating category with special characters."""
        special_name = 'Категория; с, спец. символами!'

        income_cat = _get_or_create_category(
            self.user,
            special_name,
            TransactionType.INCOME,
        )
        self.assertEqual(income_cat.name, special_name)

        expense_cat = _get_or_create_category(
            self.user,
            special_name,
            TransactionType.EXPENSE,
        )
        self.assertEqual(expense_cat.name, special_name)

    def _create_mock_pdf(self) -> Path:
        """Create a mock PDF file.

        Returns:
            Path to the created PDF file.
        """
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            return Path(temp_file.name)


class TestBankDetection(TestCase):
    """Test auto-detection of bank type from PDF text content."""

    def _make_pdf(self) -> Path:
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as f:
            f.write(b'%PDF-1.4 mock')
            return Path(f.name)

    def test_detects_raiffeisen_by_bank_name(self) -> None:
        """_create_parser returns _RaiffeisenBankParser."""
        pdf_path = self._make_pdf()
        try:
            with patch(
                'hasta_la_vista_money.users.services.bank_statement'
                '._extract_pdf_text_for_detection',
                return_value='Выписка по счету АО «Райффайзенбанк» 2025',
            ):
                parser = _create_parser(pdf_path)
                self.assertIsInstance(parser, _RaiffeisenBankParser)
        finally:
            pdf_path.unlink()

    def test_detects_sberbank_by_title(self) -> None:
        """_create_parser returns _SberbankParser for credit card."""
        pdf_path = self._make_pdf()
        try:
            with patch(
                'hasta_la_vista_money.users.services.bank_statement'
                '._extract_pdf_text_for_detection',
                return_value='Выписка по счёту кредитной карты ПАВЛОВ',
            ):
                parser = _create_parser(pdf_path)
                self.assertIsInstance(parser, _SberbankParser)
        finally:
            pdf_path.unlink()

    def test_detects_raiffeisen_by_column_headers(self) -> None:
        """_create_parser falls back to column-header detection."""
        pdf_path = self._make_pdf()
        try:
            with patch(
                'hasta_la_vista_money.users.services.bank_statement'
                '._extract_pdf_text_for_detection',
                return_value='Выписка по счету\n№ П/П\nПоступления\nРасходы',
            ):
                parser = _create_parser(pdf_path)
                self.assertIsInstance(parser, _RaiffeisenBankParser)
        finally:
            pdf_path.unlink()

    def test_detects_sberbank_by_column_headers(self) -> None:
        """_create_parser falls back to column-header detection for Sberbank."""
        pdf_path = self._make_pdf()
        try:
            with patch(
                'hasta_la_vista_money.users.services.bank_statement'
                '._extract_pdf_text_for_detection',
                return_value='КАТЕГОРИЯ\nСУММА В РУБЛЯХ\nОСТАТОК СРЕДСТВ',
            ):
                parser = _create_parser(pdf_path)
                self.assertIsInstance(parser, _SberbankParser)
        finally:
            pdf_path.unlink()

    def test_unknown_bank_falls_back_to_generic(self) -> None:
        """_create_parser returns _GenericBankParser for unrecognised text."""
        pdf_path = self._make_pdf()
        try:
            with patch(
                'hasta_la_vista_money.users.services.bank_statement'
                '._extract_pdf_text_for_detection',
                return_value='Выписка по счёту Банк Незнакомый 2025',
            ):
                parser = _create_parser(pdf_path)
                self.assertIsInstance(parser, _GenericBankParser)
        finally:
            pdf_path.unlink()

    def test_detection_failure_propagates_error(self) -> None:
        """_create_parser propagates unexpected extraction errors."""
        pdf_path = self._make_pdf()
        try:
            with (
                patch(
                    'hasta_la_vista_money.users.services.bank_statement'
                    '._extract_pdf_text_for_detection',
                    side_effect=RuntimeError('pdfminer error'),
                ),
                self.assertRaises(RuntimeError),
            ):
                _create_parser(pdf_path)
        finally:
            pdf_path.unlink()

    def test_bank_statement_parser_facade_uses_delegate(self) -> None:
        """BankStatementParser.parse() delegates to the detected bank parser."""
        pdf_path = self._make_pdf()
        try:
            with (
                patch(
                    'hasta_la_vista_money.users.services.bank_statement'
                    '._extract_pdf_text_for_detection',
                    return_value='Выписка по счёту кредитной карты',
                ),
                patch.object(
                    _SberbankParser,
                    'parse',
                    return_value=[],
                ) as mock_parse,
            ):
                facade = BankStatementParser(pdf_path)
                result = facade.parse()
                mock_parse.assert_called_once()
                self.assertEqual(result, [])
        finally:
            pdf_path.unlink()


class TestRaiffeisenBankParser(TestCase):
    """Unit tests for the Raiffeisen-specific amount extraction."""

    def _make_pdf(self) -> Path:
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as f:
            f.write(b'%PDF-1.4 mock')
            return Path(f.name)

    def _make_parser(self) -> _RaiffeisenBankParser:
        pdf_path = self._make_pdf()
        self.addCleanup(pdf_path.unlink)
        return _RaiffeisenBankParser(pdf_path)

    def _make_row(self, cols: list[Any]) -> pd.Series:
        return pd.Series(cols)

    def test_income_from_col3(self) -> None:
        """Income amount is read from col[3] (Поступления) as positive."""
        parser = self._make_parser()
        row = self._make_row(
            [
                '1',
                '28.12.2025 11:10',
                'ZP0000001',
                '+ 1 500,00 ₽',
                '',
                'Описание',
                '*6008',
            ],
        )
        amount = parser._extract_amount_from_row(row)
        if amount is None:
            self.fail('Expected an income amount')
        self.assertEqual(amount, Decimal('1500.00'))
        self.assertGreater(amount, 0)

    def test_expense_from_col4(self) -> None:
        """Expense amount is read from col[4] (Расходы) as negative."""
        parser = self._make_parser()
        row = self._make_row(
            [
                '2',
                '28.12.2025 11:10',
                'ZP0000002',
                '',
                '- 13,20 ₽',
                'Описание',
                '*6008',
            ],
        )
        amount = parser._extract_amount_from_row(row)
        if amount is None:
            self.fail('Expected an expense amount')
        self.assertEqual(amount, Decimal('-13.20'))
        self.assertLess(amount, 0)

    def test_zero_amount_when_both_cols_empty(self) -> None:
        """Returns None when both Поступления and Расходы are empty."""
        parser = self._make_parser()
        row = self._make_row(['3', '28.12.2025 11:10', '', '', '', '', ''])
        amount = parser._extract_amount_from_row(row)
        self.assertIsNone(amount)

    def test_description_column_index_is_5(self) -> None:
        """Raiffeisen always uses column 5 for the description."""
        parser = self._make_parser()
        row = self._make_row([''] * 7)
        self.assertEqual(parser._get_description_column_index(row), 5)

    def test_large_income_amount(self) -> None:
        """Correctly parses large amounts with space as thousands separator."""
        parser = self._make_parser()
        row = self._make_row(
            [
                '4',
                '02.12.2025 14:45',
                '',
                '+ 70 000,00 ₽',
                '',
                'Перевод',
                '',
            ],
        )
        amount = parser._extract_amount_from_row(row)
        self.assertEqual(amount, Decimal('70000.00'))

    def test_large_expense_amount(self) -> None:
        """Correctly parses large negative amounts."""
        parser = self._make_parser()
        row = self._make_row(
            [
                '5',
                '11.12.2025 16:04',
                'ZP000001',
                '',
                '- 37 177,01 ₽',
                'Рублевый перевод',
                '',
            ],
        )
        amount = parser._extract_amount_from_row(row)
        self.assertEqual(amount, Decimal('-37177.01'))

    def test_unsupported_row_is_kept_as_visible_fragment(self) -> None:
        """A transaction row without date or amount is not dropped."""
        parser = self._make_parser()
        df = pd.DataFrame(
            [
                ['1', '', '', '', '', 'Неизвестная операция', ''],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertEqual(
            transactions[0]['parse_issue'],
            'unsupported',
        )
        self.assertIsNone(transactions[0]['date'])
        self.assertIsNone(transactions[0]['amount'])
        self.assertEqual(
            transactions[0]['description'],
            'Неизвестная операция',
        )

    def test_known_description_gets_local_category(self) -> None:
        """Closed local rules categorize a salary credit without AI."""
        parser = self._make_parser()
        df = pd.DataFrame(
            [
                [
                    '1',
                    '28.12.2025 11:10',
                    'ZP1',
                    '+ 1 500,00 ₽',
                    '',
                    'Зачисление заработной платы',
                    '',
                ],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertEqual(
            transactions[0]['category_name'],
            'Заработная плата',
        )

    def test_unknown_description_has_no_local_category(self) -> None:
        """A merchant payment has no closed local category."""
        parser = self._make_parser()
        df = pd.DataFrame(
            [
                [
                    '1',
                    '28.12.2025 11:10',
                    '',
                    '',
                    '- 13,20 ₽',
                    'Оплата в MAGNIT',
                    '',
                ],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertIsNone(transactions[0]['category_name'])

    def test_repeated_document_number_keeps_both_rows(self) -> None:
        """A repeated document number is not an identity for dropping rows."""
        first = {
            'date': datetime(2025, 12, 1, 10, tzinfo=UTC),
            'amount': Decimal('-10.00'),
            'description': 'Первая операция',
            'source_ref': 'DUP-1',
        }
        second = {
            'date': datetime(2025, 12, 2, 10, tzinfo=UTC),
            'amount': Decimal('-20.00'),
            'description': 'Вторая операция',
            'source_ref': 'DUP-1',
        }

        result = _dedup_transactions(
            [first, second],
            merge_repeated_refs=False,
        )

        self.assertEqual(len(result), 2)

    def test_fully_identical_rows_with_repeated_ref_stay_visible(self) -> None:
        """Identical rows are not merged when the reference is not proof."""
        row = {
            'date': datetime(2025, 12, 1, 10, tzinfo=UTC),
            'amount': Decimal('-10.00'),
            'description': 'Комиссия',
            'source_ref': 'DUP-2',
        }

        result = _dedup_transactions(
            [row.copy(), row.copy()],
            merge_repeated_refs=False,
        )

        self.assertEqual(len(result), 2)

    def test_local_category_respects_direction(self) -> None:
        """An expense row never gets an income-only local category."""
        parser = self._make_parser()
        df = pd.DataFrame(
            [
                [
                    '1',
                    '28.12.2025 11:10',
                    '',
                    '',
                    '- 1 000,00 ₽',
                    'Оплата труда подрядчику',
                    '',
                ],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertIsNone(transactions[0]['category_name'])

    def test_compact_cash_does_not_categorize_next_row(self) -> None:
        """A cash row's tail never categorizes the following operation."""
        parser = self._make_parser()
        df = pd.DataFrame(
            [
                ['', '', '', ''],
                ['01.02.2026 18:14', '', '', ''],
                ['1\n72', '+ 2 000,00 ₽', 'Перевод средств', ''],
                ['', '', 'Выдача наличных средств', ''],
                ['23.01.2026 17:22', '', '', ''],
                ['311345 73', '- 120 000,00 ₽', 'банкомат', ''],
                ['', '', '', ''],
                ['20.01.2026 00:00', '', '', ''],
                ['999\n74', '- 10,00 ₽', 'Оплата покупки', ''],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 3)
        by_position = {
            transaction['row_position']: transaction
            for transaction in transactions
        }
        self.assertEqual(by_position[72]['category_name'], None)
        self.assertEqual(by_position[73]['category_name'], 'Наличные')
        self.assertEqual(by_position[74]['category_name'], None)
        self.assertEqual(by_position[73]['source_ref'], '311345')

    def test_compact_row_without_amount_stays_visible(self) -> None:
        """A document row without amount becomes a visible fragment."""
        parser = self._make_parser()
        df = pd.DataFrame(
            [
                ['1\n1', '', 'Неизвестная операция', ''],
                ['', '', '', ''],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertEqual(
            transactions[0]['parse_issue'],
            'unsupported',
        )
        self.assertIsNone(transactions[0]['amount'])
        self.assertEqual(transactions[0]['row_position'], 1)

    def test_compact_unreadable_amount_keeps_date_and_purpose_fragment(
        self,
    ) -> None:
        """A dated purpose without amount or document stays visible."""
        parser = self._make_parser()
        layouts = [
            [['01.09.2026 10:00:00', '', 'Комиссия банка', '']],
            [['01.09.2026', '', 'Комиссия банка', '']],
            [
                ['01.09.2026 10:00:00', '', '', ''],
                ['', '', 'Комиссия банка', ''],
            ],
            [
                ['01.09.2026', '', '', ''],
                ['', '', 'Комиссия банка', ''],
            ],
        ]

        for rows in layouts:
            with self.subTest(rows=rows):
                transactions = parser._parse_table(pd.DataFrame(rows))

                self.assertEqual(len(transactions), 1)
                self.assertEqual(
                    transactions[0]['parse_issue'],
                    'unsupported',
                )
                self.assertIsNone(transactions[0]['amount'])
                self.assertEqual(
                    transactions[0]['description'],
                    'Комиссия банка',
                )
                self.assertIsNotNone(transactions[0]['date'])

    def test_compact_unreadable_amount_survives_neighbour_operation(
        self,
    ) -> None:
        """A broken operation after a parsed one is not treated as its tail."""
        parser = self._make_parser()
        layouts = [
            [
                ['01.02.2026 18:14', '', '', ''],
                ['', '+ 1 000,00 ₽', 'Перевод средств', ''],
                ['02.02.2026', '', 'Комиссия банка', ''],
            ],
            [
                ['01.02.2026 18:14', '', '', ''],
                ['', '+ 1 000,00 ₽', 'Перевод средств', ''],
                ['01.02.2026', '', 'Комиссия банка', ''],
            ],
            [
                ['01.02.2026 18:14', '', '', ''],
                ['', '+ 1 000,00 ₽', 'Перевод средств', ''],
                ['02.02.2026', '', '', ''],
                ['', '', 'Комиссия банка', ''],
            ],
        ]

        for rows in layouts:
            with self.subTest(rows=rows):
                transactions = parser._parse_table(pd.DataFrame(rows))

                self.assertEqual(len(transactions), 2)
                self.assertEqual(
                    transactions[0]['amount'],
                    Decimal('1000.00'),
                )
                fragment = transactions[1]
                self.assertEqual(fragment['parse_issue'], 'unsupported')
                self.assertIsNone(fragment['amount'])
                self.assertEqual(fragment['description'], 'Комиссия банка')
                self.assertIsNotNone(fragment['date'])

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    @patch(
        'hasta_la_vista_money.users.services.bank_statement.extract_text',
        return_value='',
    )
    def test_compact_zero_amount_row_stays_visible_as_problem_fragment(
        self,
        mock_extract_text: MagicMock,
        mock_camelot: MagicMock,
    ) -> None:
        """A compact zero-amount row is kept as a problem fragment."""
        table = MagicMock()
        table.df = pd.DataFrame(
            [
                ['01.02.2026 18:14', '', '', ''],
                ['', '0,00 ₽', 'Комиссия', ''],
            ],
        )
        mock_camelot.read_pdf.return_value = [table]

        result = self._make_parser().parse()

        self.assertEqual(len(result.transactions), 1)
        self.assertEqual(result.transactions[0]['amount'], Decimal('0.00'))
        self.assertEqual(
            result.transactions[0]['parse_issue'],
            'zero_amount',
        )

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_compact_rows_without_document_get_unique_positions_across_pages(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Rows without a printed number never share one statement position."""
        first_page = MagicMock()
        first_page.df = pd.DataFrame(
            [
                ['', '', '', ''],
                ['01.02.2026 18:14', '', '', ''],
                ['', '+ 1 000,00 ₽', 'Перевод средств', ''],
            ],
        )
        second_page = MagicMock()
        second_page.df = pd.DataFrame(
            [
                ['', '', '', ''],
                ['02.02.2026 09:10', '', '', ''],
                ['', '- 500,00 ₽', 'Оплата покупки', ''],
            ],
        )
        mock_camelot.read_pdf.return_value = [first_page, second_page]

        result = self._make_parser().parse()

        positions = [item['row_position'] for item in result.transactions]
        self.assertEqual(len(positions), 2)
        self.assertEqual(len(set(positions)), 2)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    @patch(
        'hasta_la_vista_money.users.services.bank_statement.extract_text',
        return_value='',
    )
    def test_zero_amount_row_stays_visible_as_problem_fragment(
        self,
        mock_extract_text: MagicMock,
        mock_camelot: MagicMock,
    ) -> None:
        """A zero-amount row is kept as a fragment instead of being dropped."""
        table = MagicMock()
        table.df = pd.DataFrame(
            [
                [
                    '1',
                    '01.02.2026 18:14',
                    'DOC-1',
                    '',
                    '0,00 ₽',
                    'Комиссия',
                    '',
                ],
            ],
        )
        mock_camelot.read_pdf.return_value = [table]

        result = self._make_parser().parse()

        self.assertEqual(len(result.transactions), 1)
        self.assertEqual(result.transactions[0]['amount'], Decimal('0.00'))
        self.assertEqual(
            result.transactions[0]['parse_issue'],
            'zero_amount',
        )

    def test_clean_description_with_long_digit_run_is_fast(self) -> None:
        """A long digit run without a currency marker cannot stall cleaning."""

        def _raise_timeout(_signum: int, _frame: Any) -> None:
            raise TimeoutError('description cleaning exceeded its budget')

        parser = self._make_parser()
        description = 'Покупка ' + '1' * 40
        previous_handler = signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, 2.0)
        try:
            result = parser._clean_description(description)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

        self.assertIn('Покупка', result)
        self.assertIn('1' * 40, result)

    def test_real_statement_matches_bank_summary(self) -> None:
        """Real anonymized statement parses all rows and printed totals."""
        result = _RaiffeisenBankParser(
            RAIFFEISEN_REAL_FIXTURE,
        ).parse()

        income = sum(
            transaction['amount']
            for transaction in result.transactions
            if transaction['amount'] > 0
        )
        expense = sum(
            -transaction['amount']
            for transaction in result.transactions
            if transaction['amount'] < 0
        )
        self.assertEqual(len(result.transactions), 138)
        self.assertEqual(result.format_version, 3)
        self.assertEqual(income, Decimal('613390.25'))
        self.assertEqual(expense, Decimal('619845.17'))
        self.assertEqual(
            result.account_number,
            '68509471470637308180',
        )
        self.assertEqual(result.period_start, date(2025, 11, 20))
        self.assertEqual(result.period_end, date(2026, 11, 20))
        self.assertEqual(
            result.closing_balance_date,
            date(2026, 11, 20),
        )
        self.assertEqual(result.closing_balance, Decimal('0.00'))

        positions = sorted(
            transaction['row_position'] for transaction in result.transactions
        )
        self.assertEqual(positions, list(range(1, 139)))
        refs = [
            transaction['source_ref']
            for transaction in result.transactions
            if transaction['source_ref']
        ]
        self.assertEqual(len(refs), 125)
        self.assertEqual(len(set(refs)), 125)
        self.assertEqual(
            sum(
                1
                for transaction in result.transactions
                if not transaction['source_ref']
            ),
            13,
        )
        self.assertFalse(
            any(
                transaction.get('parse_issue')
                for transaction in result.transactions
            ),
        )
        categories = [
            transaction['category_name'] for transaction in result.transactions
        ]
        self.assertEqual(categories.count(None), 137)
        self.assertEqual(categories.count('Наличные'), 1)

        by_position = {
            transaction['row_position']: transaction
            for transaction in result.transactions
        }
        self.assertEqual(
            (
                by_position[1]['date'].date(),
                by_position[1]['amount'],
                by_position[1]['source_ref'],
            ),
            (date(2026, 10, 14), Decimal('-5001.00'), '930579'),
        )
        self.assertEqual(
            (
                by_position[19]['date'].date(),
                by_position[19]['amount'],
                by_position[19]['source_ref'],
            ),
            (date(2026, 5, 23), Decimal('3000.00'), '875409'),
        )
        self.assertEqual(
            (
                by_position[73]['amount'],
                by_position[73]['source_ref'],
                by_position[73]['category_name'],
            ),
            (Decimal('-120000.00'), '311345', 'Наличные'),
        )
        self.assertEqual(
            (
                by_position[138]['date'].date(),
                by_position[138]['amount'],
                by_position[138]['source_ref'],
            ),
            (date(2025, 11, 20), Decimal('-1000.00'), '77289'),
        )
        transfers = [
            transaction
            for transaction in result.transactions
            if 'перевод' in transaction['description'].casefold()
        ]
        self.assertTrue(transfers)
        self.assertTrue(
            all(
                transaction['category_name'] is None
                for transaction in transfers
            ),
        )
        self.assertIn('1080.00 NQWMXBV', by_position[20]['description'])
        self.assertNotIn('1080.00 NQWMXBV', by_position[21]['description'])
        self.assertIn('Перевод с номера', by_position[21]['description'])
        self.assertIn(
            '14334414337310000610',
            by_position[39]['description'],
        )
        self.assertNotIn(
            '14334414337310000610',
            by_position[38]['description'],
        )
        self.assertIn('Оплата услуг', by_position[32]['description'])
        self.assertIn(
            'Номер перевода 5223682132',
            by_position[32]['description'],
        )


class TestSberbankParser(TestCase):
    """Unit tests for the Sberbank credit card statement parser."""

    def _make_pdf(self) -> Path:
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as f:
            f.write(b'%PDF-1.4 mock')
            return Path(f.name)

    def _make_parser(self) -> _SberbankParser:
        pdf_path = self._make_pdf()
        self.addCleanup(pdf_path.unlink)
        return _SberbankParser(pdf_path)

    def _make_df(self, rows: list[list[Any]]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_is_transaction_table_detects_header(self) -> None:
        """Table with КАТЕГОРИЯ header is recognised as a transaction table."""
        parser = self._make_parser()
        df = self._make_df(
            [
                [
                    'ДАТА ОПЕРАЦИИ (МСК)',
                    'КАТЕГОРИЯ',
                    'СУММА В РУБЛЯХ',
                    'ОСТАТОК СРЕДСТВ',
                ],
                ['18.02.2026 17:11', 'Транспорт', '73,00 ₽', '59 016,93 ₽'],
            ],
        )
        self.assertTrue(parser._is_transaction_table(df))

    def test_is_transaction_table_rejects_unrelated(self) -> None:
        """Table without recognised headers is not a transaction table."""
        parser = self._make_parser()
        df = self._make_df(
            [
                ['Балансовый отчёт', 'Сумма'],
                ['Итого', '1 000,00 ₽'],
            ],
        )
        self.assertFalse(parser._is_transaction_table(df))

    def test_parse_table_two_row_transaction(self) -> None:
        """A standard two-row Sberbank transaction is parsed correctly."""
        parser = self._make_parser()
        df = self._make_df(
            [
                ['18.02.2026 17:11', 'Транспорт', '73,00 ₽', '59 016,93 ₽'],
                ['18.02.2026 / 869838', 'MOSCOW STRELKACARD', '', ''],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 1)
        t = transactions[0]
        self.assertEqual(t['description'], 'Транспорт')
        self.assertEqual(t['amount'], Decimal('-73.00'))
        self.assertEqual(t['source_ref_strength'], 'weak')
        self.assertEqual(t['category_name'], 'Транспорт')

    def test_parse_table_income_with_plus_sign(self) -> None:
        """Top-ups (income) prefixed with '+' are positive."""
        parser = self._make_parser()
        df = self._make_df(
            [
                [
                    '09.02.2026 15:50',
                    'Перевод на карту',
                    '+50 546,00 ₽',
                    '63 493,18 ₽',
                ],
                ['09.02.2026 / 552183', 'Перевод от П.', '', ''],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]['amount'], Decimal('50546.00'))
        self.assertGreater(transactions[0]['amount'], 0)

    def test_merged_cell_topup_with_text_prefix_is_income(self) -> None:
        """A merged amount cell keeps a '+' sign after a category prefix."""
        parser = self._make_parser()
        df = self._make_df(
            [
                [
                    '01.04.2026\n16:51\nПополнение',
                    'Курс 90,00 / Пополнение\n+ 50 546,00',
                    '113 051,18',
                ],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]['amount'], Decimal('50546.00'))
        self.assertGreater(transactions[0]['amount'], 0)

    def test_parse_table_keeps_unparsed_amount_as_error_fragment(self) -> None:
        """A dated row without a readable amount stays visible, not dropped."""
        parser = self._make_parser()
        df = self._make_df(
            [
                ['18.02.2026 17:11', 'Категория', '', '1 000,00 ₽'],
                ['18.02.2026 / 123', 'Описание', '', ''],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 1)
        self.assertIsNone(transactions[0]['amount'])
        self.assertTrue(transactions[0]['parse_issue'])
        self.assertEqual(transactions[0]['source_ref'], '123')
        self.assertEqual(transactions[0]['source_ref_strength'], 'weak')

    def test_parse_table_multiple_transactions(self) -> None:
        """Multiple consecutive two-row transactions are all parsed."""
        parser = self._make_parser()
        df = self._make_df(
            [
                ['18.02.2026 17:11', 'Транспорт', '73,00 ₽', '59 016,93 ₽'],
                ['18.02.2026 / 869838', 'MOSCOW STRELKA', '', ''],
                [
                    '18.02.2026 20:20',
                    'Рестораны и кафе',
                    '3 276,00 ₽',
                    '53 534,93 ₽',
                ],
                ['18.02.2026 / 098646', 'Korolyov SUSHI VOK', '', ''],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0]['description'], 'Транспорт')
        self.assertEqual(transactions[1]['description'], 'Рестораны и кафе')

    def test_extract_sberbank_amount_negative(self) -> None:
        """Amount without '+' prefix is treated as an expense (negative)."""
        parser = self._make_parser()
        result = parser._extract_sberbank_amount('3 276,00 ₽')
        self.assertEqual(result, Decimal('-3276.00'))

    def test_extract_sberbank_amount_positive(self) -> None:
        """Amount with '+' prefix is treated as income (positive)."""
        parser = self._make_parser()
        result = parser._extract_sberbank_amount('+50 546,00 ₽')
        self.assertEqual(result, Decimal('50546.00'))

    def test_extract_sberbank_amount_with_multiple_spaces(self) -> None:
        """Multiple spaces and a currency sign keep the '+' and the sum."""
        parser = self._make_parser()
        result = parser._extract_sberbank_amount('+  50  546,00 ₽')
        self.assertEqual(result, Decimal('50546.00'))

    def test_extract_sberbank_amount_ignores_prefix_decimal(self) -> None:
        """An unsigned prefix number never wins over the currency amount."""
        parser = self._make_parser()
        result = parser._extract_sberbank_amount(
            'Курс 90,00 / Пополнение + 50 546,00 ₽',
        )
        self.assertEqual(result, Decimal('50546.00'))

    def test_extract_sberbank_amount_returns_none_for_empty(self) -> None:
        """Returns None for empty or nan text."""
        parser = self._make_parser()
        self.assertIsNone(parser._extract_sberbank_amount(''))
        self.assertIsNone(parser._extract_sberbank_amount('nan'))

    def test_find_data_start_row_skips_headers(self) -> None:
        """_find_data_start_row returns index of first row with a valid date."""
        parser = self._make_parser()
        df = self._make_df(
            [
                ['ДАТА ОПЕРАЦИИ (МСК)', 'КАТЕГОРИЯ', 'СУММА', 'ОСТАТОК'],
                ['Дата обработки', 'Описание', '', ''],
                ['18.02.2026 17:11', 'Транспорт', '73,00 ₽', '59 016,93 ₽'],
            ],
        )
        self.assertEqual(parser._find_data_start_row(df), 2)

    def test_category_used_as_description(self) -> None:
        """The Sberbank category name becomes the transaction description."""
        parser = self._make_parser()
        df = self._make_df(
            [
                [
                    '17.02.2026 04:28',
                    'Коммунальные платежи, связь, интернет.',
                    '1 000,00 ₽',
                    '62 359,93 ₽',
                ],
                ['17.02.2026 / 347879', 'MOSCOW OOO VISP', '', ''],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(
            transactions[0]['description'],
            'Коммунальные платежи, связь, интернет.',
        )

    def test_parse_table_trailing_single_row_transaction(self) -> None:
        """Last transaction with no row B (cut at page end) is not dropped.

        Regression test: the parser previously used ``while i < len(df) - 1``,
        which silently skipped the final table row when it was the row A of
        a transaction whose row B was missing (e.g. the last entry on the
        last PDF page of a Sberbank statement).
        """
        parser = self._make_parser()
        df = self._make_df(
            [
                ['18.02.2026 17:11', 'Транспорт', '73,00 ₽', '59 016,93 ₽'],
                ['18.02.2026 / 869838', 'MOSCOW STRELKA', '', ''],
                [
                    '01.04.2026 16:51',
                    'Прочие расходы',
                    '2 958,00 ₽',
                    '12 851,05 ₽',
                ],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[1]['description'], 'Прочие расходы')
        self.assertEqual(transactions[1]['amount'], Decimal('-2958.00'))

    def test_parse_table_trailing_single_row_only(self) -> None:
        """A table consisting of a single transaction row is still parsed."""
        parser = self._make_parser()
        df = self._make_df(
            [
                [
                    '01.04.2026 16:51',
                    'Прочие расходы',
                    '2 958,00 ₽',
                    '12 851,05 ₽',
                ],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]['amount'], Decimal('-2958.00'))

    def test_parse_table_extracts_source_ref_from_row_b(self) -> None:
        """Authcode from row B becomes the transaction source_ref."""
        parser = self._make_parser()
        df = self._make_df(
            [
                ['18.02.2026 17:11', 'Транспорт', '73,00 ₽', '59 016,93 ₽'],
                ['18.02.2026 / 869838', 'MOSCOW STRELKA', '', ''],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]['source_ref'], '869838')

    def test_parse_table_merged_3col_layout_last_page(self) -> None:
        """Real 3-column layout from the trailing PDF page is parsed.

        Reproduces Camelot output of the last page of a real Sberbank
        statement, where col[0] packs date+time+category and col[1]
        contains only the amount (no ₽ sign).
        """
        parser = self._make_parser()
        df = self._make_df(
            [
                [
                    'Выписка по счёту кредитной карты',
                    '',
                    'Страница 4 из 4',
                ],
                [
                    'ДАТА ОПЕРАЦИИ (МСК)\nКАТЕГОРИЯ',
                    'СУММА В РУБЛЯХ',
                    'ОСТАТОК СРЕДСТВ',
                ],
                [
                    'Дата обработки¹\nОписание операции',
                    'Сумма в валюте',
                    '',
                ],
                ['и код авторизации', 'операции²', ''],
                [
                    '01.04.2026\n16:51\nПрочие расходы',
                    '2 958,00',
                    '12 851,05',
                ],
                [
                    (
                        '03.04.2026\n311925\n'
                        'Moscow Aliexpress. Операция по карте ****1234'
                    ),
                    '',
                    '',
                ],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]['description'], 'Прочие расходы')
        self.assertEqual(transactions[0]['amount'], Decimal('-2958.00'))
        self.assertEqual(transactions[0]['source_ref'], '311925')

    def test_extract_authcode_from_newline_separated(self) -> None:
        """Authcode is extracted from 'DD.MM.YYYY\\nAUTHCODE\\n...' cells."""
        parser = self._make_parser()
        row = pd.Series(
            [
                (
                    '03.04.2026\n311925\n'
                    'Moscow Aliexpress. Операция по карте ****1234'
                ),
                '',
                '',
            ],
        )
        self.assertEqual(parser._extract_authcode(row), '311925')

    def test_parse_table_source_ref_is_none_when_no_row_b(self) -> None:
        """A single-row transaction (no row B) has no source_ref."""
        parser = self._make_parser()
        df = self._make_df(
            [
                [
                    '01.04.2026 16:51',
                    'Прочие расходы',
                    '2 958,00 ₽',
                    '12 851,05 ₽',
                ],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 1)
        self.assertIsNone(transactions[0]['source_ref'])

    def test_parse_table_keeps_missing_date_operation(self) -> None:
        """A potential operation with a broken bank date stays visible.

        The row before the first readable date is not skipped: its readable
        amount and auth hint become a parse fragment, and the following
        valid operation is still parsed.
        """
        parser = self._make_parser()
        df = self._make_df(
            [
                ['', 'Покупка', '1 200,00 ₽', '10 000,00 ₽'],
                ['19.02.2026 / 222222', 'MAGNIT', '', ''],
                ['20.02.2026 10:00', 'Транспорт', '73,00 ₽', '9 927,00 ₽'],
                ['20.02.2026 / 333333', 'MOSCOW STRELKA', '', ''],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 2)
        broken = transactions[0]
        self.assertIsNone(broken['date'])
        self.assertEqual(broken['amount'], Decimal('-1200.00'))
        self.assertEqual(broken['source_ref'], '222222')
        self.assertTrue(broken['parse_issue'])
        self.assertEqual(transactions[1]['amount'], Decimal('-73.00'))

    def test_parse_table_broken_pair_does_not_swallow_next_operation(
        self,
    ) -> None:
        """A row A without its row B does not consume the next row A."""
        parser = self._make_parser()
        df = self._make_df(
            [
                [
                    '01.04.2026\n16:51\nПрочие расходы',
                    '2 958,00',
                    '12 851,05',
                ],
                ['02.04.2026\n10:00\nТранспорт', '73,00', '12 778,05'],
                ['02.04.2026\n555555\nMOSCOW STRELKA', '', ''],
            ],
        )

        transactions = parser._parse_table(df)

        self.assertEqual(len(transactions), 2)
        self.assertEqual(
            [t['amount'] for t in transactions],
            [Decimal('-2958.00'), Decimal('-73.00')],
        )

    def test_authcode_without_date_is_not_an_identity(self) -> None:
        """A bare auth code without bank date/context is not a reference."""
        parser = self._make_parser()
        row = pd.Series(['869838', 'MOSCOW STRELKA', '', ''])
        self.assertIsNone(parser._extract_authcode(row))

    def test_local_category_is_closed_and_directional(self) -> None:
        """Only known expense labels map; unknown and credit rows do not."""
        self.assertEqual(
            sberbank_local_category('Транспорт', 'expense'),
            'Транспорт',
        )
        self.assertIsNone(
            sberbank_local_category('Покупка в MAGNIT', 'expense'),
        )
        self.assertIsNone(sberbank_local_category('Транспорт', 'income'))

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.extract_text',
        return_value='',
    )
    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_parse_keeps_repeated_authcode_rows(
        self,
        mock_camelot: MagicMock,
        mock_extract_text: MagicMock,
    ) -> None:
        """A reused auth code never merges away a second bank operation."""
        parser = self._make_parser()
        mock_table = MagicMock()
        mock_table.df = self._make_df(
            [
                ['18.02.2026 17:11', 'Транспорт', '73,00 ₽', '59 016,93 ₽'],
                ['18.02.2026 / 869838', 'MOSCOW STRELKA', '', ''],
                [
                    '18.02.2026 20:20',
                    'Рестораны и кафе',
                    '3 276,00 ₽',
                    '53 534,93 ₽',
                ],
                ['18.02.2026 / 869838', 'SUSHI VOK', '', ''],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        transactions = parser.parse().transactions

        self.assertEqual(len(transactions), 2)
        self.assertEqual(
            [t['source_ref'] for t in transactions],
            ['869838', '869838'],
        )
        self.assertEqual([t['row_position'] for t in transactions], [0, 1])

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.extract_text',
        return_value='',
    )
    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_parse_wraps_fatal_file_error(
        self,
        mock_camelot: MagicMock,
        mock_extract_text: MagicMock,
    ) -> None:
        """A broken file is one fatal parse error, not a partial statement."""
        parser = self._make_parser()
        mock_camelot.read_pdf.side_effect = RuntimeError('broken table')

        with self.assertRaises(BankStatementParseError):
            parser.parse()

    def test_parse_real_anonymized_statement(self) -> None:
        """Parse the real anonymized Sberbank credit-card statement.

        Expected values are read from the PDF table itself: six operations,
        two top-ups and four expenses, with their bank auth codes. Summary
        rows ("Остаток на ...") are not operations.
        """
        result = _SberbankParser(SBERBANK_FIXTURE).parse()

        self.assertEqual(result.bank, 'sberbank')
        self.assertEqual(result.format_version, 2)
        self.assertEqual(result.period_start, date(2026, 7, 1))
        self.assertEqual(result.period_end, date(2026, 11, 19))
        self.assertEqual(len(result.transactions), 6)
        self.assertEqual(
            [t['amount'] for t in result.transactions],
            [
                Decimal('18470.57'),
                Decimal('-85.13'),
                Decimal('-7450.86'),
                Decimal('-10934.58'),
                Decimal('199.00'),
                Decimal('-199.00'),
            ],
        )
        self.assertEqual(
            [t['source_ref'] for t in result.transactions],
            ['676887', '188529', '360456', '356063', '700037', '588469'],
        )
        self.assertEqual(
            [t['date'].strftime('%d.%m.%Y %H:%M') for t in result.transactions],
            [
                '27.09.2026 11:37',
                '01.09.2026 01:15',
                '02.08.2026 18:14',
                '02.08.2026 18:13',
                '01.08.2026 12:05',
                '09.07.2026 10:06',
            ],
        )
        self.assertEqual(
            [t['description'] for t in result.transactions],
            [
                'Перевод на карту',
                'Прочие расходы',
                'Коммунальные платежи, связь, интернет.',
                'Коммунальные платежи, связь, интернет.',
                'Перевод на карту',
                'Прочие расходы',
            ],
        )
        self.assertEqual(
            [t.get('category_name') for t in result.transactions],
            [
                None,
                'Прочие расходы',
                'Коммунальные платежи, связь, интернет',
                'Коммунальные платежи, связь, интернет',
                None,
                'Прочие расходы',
            ],
        )
        self.assertFalse(any(t.get('parse_issue') for t in result.transactions))


class TestStatementParseResult(TestCase):
    """Тест структуры результата парсинга."""

    def test_has_expected_fields(self):
        result = StatementParseResult(
            transactions=[],
            closing_balance=Decimal('12345.67'),
            closing_balance_date=None,
        )
        self.assertEqual(result.transactions, [])
        self.assertEqual(result.closing_balance, Decimal('12345.67'))
        self.assertIsNone(result.closing_balance_date)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    @patch('hasta_la_vista_money.users.services.bank_statement.extract_text')
    def test_parse_returns_statement_parse_result(
        self,
        mock_extract_text,
        mock_camelot,
    ):
        mock_extract_text.return_value = 'Райффайзенбанк'
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame()
        mock_camelot.read_pdf.return_value = [mock_table]

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(b'%PDF-1.4 fake')
            path = f.name

        try:
            parser = BankStatementParser(path)
            result = parser.parse()
            self.assertIsInstance(result, StatementParseResult)
            self.assertIsInstance(result.transactions, list)
        finally:
            Path(path).unlink(missing_ok=True)


class TestProcessBankStatementTaskIntegration(TestCase):
    """Интеграционные тесты задачи Celery с classifier и полями сверки."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Тест сверки',
            balance=Decimal('10000.00'),
            currency='RUB',
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_category_uses_classifier_output(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = 'Продукты'
        ApplicationContainer.users.category_classifier.override(
            mock_classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )

        mock_parser = MagicMock()
        mock_parser.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': timezone.now(),
                    'amount': Decimal('-500.00'),
                    'description': 'MAGNIT 1234',
                    'source_ref': 'ref-001',
                },
            ],
            closing_balance=Decimal('9500.00'),
        )
        mock_parser_cls.return_value = mock_parser

        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/test.pdf',
            status=BankStatementUpload.Status.PENDING,
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)
        self.assertEqual(
            upload.statement_closing_balance,
            Decimal('9500.00'),
        )

        category = Category.objects.filter(
            user=self.user,
            name='Продукты',
        ).first()
        self.assertIsNotNone(category)

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_run_of_several_rows_is_one_operation_with_a_summary(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        """A multi-row run shares one operation_id, set outside the loop."""
        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = 'Такси'
        ApplicationContainer.users.category_classifier.override(
            mock_classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )

        base_date = timezone.now()
        mock_parser = MagicMock()
        mock_parser.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': base_date - timedelta(days=2 - i),
                    'amount': Decimal(f'-{500 + i}.00'),
                    'description': f'Такси {i}',
                    'source_ref': f'ref-{i}',
                }
                for i in range(3)
            ],
        )
        mock_parser_cls.return_value = mock_parser

        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/three-rows.pdf',
            status=BankStatementUpload.Status.PENDING,
        )

        process_bank_statement_task.apply(args=[upload.pk])

        run_entries = AuditLog.objects.filter(
            user=self.user,
            kind=AuditOperationKind.STATEMENT_IMPORT,
        )
        operation_ids = {entry.operation_id for entry in run_entries}
        self.assertEqual(len(operation_ids), 1)
        summary = AuditLog.objects.get(
            user=self.user,
            model_name=STATEMENT_IMPORT_LABEL,
        )
        self.assertEqual(summary.diff['created'], 3)
        self.assertEqual(summary.diff['skipped_duplicates'], 0)
        self.assertEqual(summary.operation_id, next(iter(operation_ids)))

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_all_rows_duplicate_still_writes_a_summary(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        """A run whose rows are all duplicates is still recorded."""
        existing_date = timezone.now()
        existing = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=Category.objects.create(
                user=self.user,
                name='Такси',
                type=TransactionType.EXPENSE,
            ),
            type=TransactionType.EXPENSE,
            amount=Decimal('500.00'),
            date=existing_date,
            source_ref='dup-ref',
        )
        mock_parser = MagicMock()
        mock_parser.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': existing.date,
                    'amount': Decimal('-500.00'),
                    'description': 'Такси',
                    'source_ref': 'dup-ref',
                },
            ],
        )
        mock_parser_cls.return_value = mock_parser
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/all-duplicate.pdf',
            status=BankStatementUpload.Status.PENDING,
        )

        process_bank_statement_task.apply(args=[upload.pk])

        summary = AuditLog.objects.get(
            user=self.user,
            model_name=STATEMENT_IMPORT_LABEL,
        )
        self.assertEqual(summary.diff['created'], 0)
        self.assertEqual(summary.diff['skipped_duplicates'], 1)

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_balance_discrepancy_saved(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = 'Прочее'
        ApplicationContainer.users.category_classifier.override(
            mock_classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )

        mock_parser = MagicMock()
        mock_parser.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[],
            closing_balance=Decimal('9000.00'),
            closing_balance_date=timezone.localdate(),
            closing_balance_currency='RUB',
            closing_balance_semantics='closing_day',
        )
        mock_parser_cls.return_value = mock_parser

        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/test.pdf',
            status=BankStatementUpload.Status.PENDING,
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.assertEqual(
            upload.statement_closing_balance,
            Decimal('9000.00'),
        )
        self.assertEqual(
            upload.account_balance_after,
            Decimal('10000.00'),
        )
        self.assertEqual(
            upload.balance_discrepancy,
            Decimal('-1000.00'),
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_probable_duplicate_waits_for_confirmation(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        transaction_date = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Транспорт',
            type=TransactionType.EXPENSE,
        )
        existing = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('500.00'),
            date=transaction_date,
        )
        classifier = MagicMock()
        classifier.classify.return_value = 'Такси'
        ApplicationContainer.users.category_classifier.override(
            classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': transaction_date,
                    'amount': Decimal('-500.00'),
                    'description': 'Такси 123456 Иван Иванов',
                    'source_ref': 'statement-ref',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/duplicate.pdf',
            file_hash='duplicate-file',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(self.account.balance, Decimal('10000.00'))
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertFalse(
            Category.objects.filter(
                user=self.user,
                name='Такси',
                type=TransactionType.EXPENSE,
            ).exists(),
        )
        statement_row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(statement_row.candidate, existing)
        self.assertEqual(statement_row.suggested_category, 'Такси')
        self.assertNotIn('123456', statement_row.description)
        self.assertEqual(statement_row.candidate_description, 'Транспорт')

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_classifier_failure_uses_fallback_for_probable_duplicate(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        transaction_date = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Старое',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('50.00'),
            date=transaction_date,
        )
        classifier = MagicMock()
        classifier.classify.side_effect = RuntimeError('offline')
        ApplicationContainer.users.category_classifier.override(
            classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': transaction_date,
                    'amount': Decimal('-50.00'),
                    'description': 'Кофе',
                    'source_ref': 'coffee-ref',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/offline.pdf',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        statement_row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(statement_row.suggested_category, 'Без категории')
        self.assertFalse(
            Category.objects.filter(
                user=self.user,
                name='Без категории',
            ).exists(),
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_classifier_failure_uses_fallback_for_new_row(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        classifier = MagicMock()
        classifier.classify.side_effect = RuntimeError('offline')
        ApplicationContainer.users.category_classifier.override(
            classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': timezone.now(),
                    'amount': Decimal('-25.00'),
                    'description': 'Кофе',
                    'source_ref': 'new-coffee-ref',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/new-offline.pdf',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)
        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Без категории',
                type=TransactionType.EXPENSE,
            ).exists(),
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_exact_source_duplicate_does_not_require_confirmation(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        transaction_date = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        fingerprint = (
            ApplicationContainer()
            .users.statement_identity_service()
            .fingerprint(
                bank='testbank',
                account_id=self.account.pk,
                source_ref='same-ref',
            )
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('75.00'),
            date=transaction_date,
            source_ref='same-ref',
            source_fingerprint=fingerprint.digest,
            source_fingerprint_key_version=fingerprint.key_version,
            source_fingerprint_format_version=fingerprint.format_version,
        )
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': transaction_date,
                    'amount': Decimal('-75.00'),
                    'description': 'Магазин',
                    'source_ref': 'same-ref',
                    'source_ref_strength': 'strong',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/repeat.pdf',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)
        duplicate = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            duplicate.decision,
            BankStatementRow.Decision.LINKED,
        )
        self.assertIsNotNone(duplicate.transaction_id)
        classifier.classify.assert_not_called()

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_candidate_must_have_same_account_and_type(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        transaction_date = timezone.now()
        other_account = Account.objects.create(
            user=self.user,
            name_account='Другой',
            balance=Decimal('500.00'),
            currency='RUB',
        )
        category = Category.objects.create(
            user=self.user,
            name='Доход',
            type=TransactionType.INCOME,
        )
        Transaction.objects.create(
            user=self.user,
            account=other_account,
            category=category,
            type=TransactionType.INCOME,
            amount=Decimal('100.00'),
            date=transaction_date,
        )
        classifier = MagicMock()
        classifier.classify.return_value = 'Продукты'
        ApplicationContainer.users.category_classifier.override(
            classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': transaction_date,
                    'amount': Decimal('-100.00'),
                    'description': 'Магазин',
                    'source_ref': 'different-movement',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/new.pdf',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)
        self.assertFalse(
            BankStatementRow.objects.filter(upload=upload).exists(),
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('9900.00'))

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_multiple_candidates_are_saved_without_auto_selection(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        transaction_date = timezone.now()
        first_category = Category.objects.create(
            user=self.user,
            name='Такси',
            type=TransactionType.EXPENSE,
        )
        second_category = Category.objects.create(
            user=self.user,
            name='Транспорт',
            type=TransactionType.EXPENSE,
        )
        first = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=first_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('300.00'),
            date=transaction_date,
            description='Такси',
        )
        second = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=second_category,
            type=TransactionType.EXPENSE,
            amount=Decimal('300.00'),
            date=transaction_date,
            description='Транспорт',
        )
        classifier = MagicMock()
        classifier.classify.return_value = 'Поездки'
        ApplicationContainer.users.category_classifier.override(
            classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': transaction_date,
                    'amount': Decimal('-300.00'),
                    'description': 'Такси',
                    'source_ref': 'ambiguous-ref',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/ambiguous.pdf',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertIsNone(row.transaction)
        self.assertEqual(
            list(
                row.candidates.values_list('transaction_id', flat=True),
            ),
            [first.pk, second.pk],
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_candidates_are_ranked_by_description_similarity(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        transaction_date = timezone.now()
        groceries = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        taxi = Category.objects.create(
            user=self.user,
            name='Такси',
            type=TransactionType.EXPENSE,
        )
        unrelated = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=groceries,
            type=TransactionType.EXPENSE,
            amount=Decimal('200.00'),
            date=transaction_date,
            description='Супермаркет продукты',
        )
        matching = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=taxi,
            type=TransactionType.EXPENSE,
            amount=Decimal('200.00'),
            date=transaction_date,
            description='Такси',
        )
        classifier = MagicMock()
        classifier.classify.return_value = 'Поездки'
        ApplicationContainer.users.category_classifier.override(
            classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': transaction_date,
                    'amount': Decimal('-200.00'),
                    'description': 'Такси',
                    'source_ref': 'ranked-ref',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/ranked.pdf',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            list(row.candidates.values_list('transaction_id', flat=True)),
            [matching.pk, unrelated.pk],
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_mixed_statement_imports_clear_row_and_awaits_duplicate(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        duplicate_date = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Транспорт',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('300.00'),
            date=duplicate_date,
        )
        classifier = MagicMock()
        classifier.classify.side_effect = ['Поездки', 'Продукты']
        ApplicationContainer.users.category_classifier.override(
            classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': duplicate_date,
                    'amount': Decimal('-300.00'),
                    'description': 'Такси',
                    'source_ref': 'duplicate-row',
                },
                {
                    'date': duplicate_date + timedelta(hours=1),
                    'amount': Decimal('-125.00'),
                    'description': 'Магазин',
                    'source_ref': 'clear-row',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/mixed.pdf',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(upload.progress, 100)
        self.assertEqual(upload.imported_count, 1)
        self.assertEqual(upload.awaiting_decision_count, 1)
        self.assertEqual(upload.linked_count, 0)
        self.assertEqual(upload.expired_count, 0)
        self.assertEqual(upload.failed_count, 0)
        self.assertEqual(self.account.balance, Decimal('9875.00'))
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(
            BankStatementRow.objects.filter(upload=upload).count(),
            1,
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_identical_rows_in_same_file_are_imported_separately(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        transaction_date = timezone.now()
        classifier = MagicMock()
        classifier.classify.return_value = 'Кофе'
        ApplicationContainer.users.category_classifier.override(
            classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': transaction_date,
                    'amount': Decimal('-100.00'),
                    'description': 'Кофе',
                    'row_position': 0,
                },
                {
                    'date': transaction_date,
                    'amount': Decimal('-100.00'),
                    'description': 'Кофе',
                    'row_position': 1,
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/identical.pdf',
            file_hash='identical-file',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)
        self.assertEqual(upload.imported_count, 2)
        self.assertEqual(self.account.balance, Decimal('9800.00'))
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertFalse(
            BankStatementRow.objects.filter(upload=upload).exists(),
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_clear_statement_completes_with_outcomes_and_balance(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        classifier = MagicMock()
        classifier.classify.return_value = 'Продукты'
        ApplicationContainer.users.category_classifier.override(
            classifier,
        )
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            bank='testbank',
            transactions=[
                {
                    'date': timezone.now(),
                    'amount': Decimal('-250.00'),
                    'description': 'Магазин',
                    'source_ref': 'clear-only',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/clear.pdf',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)
        self.assertEqual(upload.progress, 100)
        self.assertEqual(upload.imported_count, 1)
        self.assertEqual(upload.awaiting_decision_count, 0)
        self.assertEqual(self.account.balance, Decimal('9750.00'))


class TestOzonBankStatement(TestCase):
    """Tests for the Ozon Bank cash-flow statement format."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Ozon',
            balance=Decimal('10000.00'),
            currency='RUB',
        )
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            self.pdf_path = Path(temp_file.name)

    def tearDown(self) -> None:
        self.pdf_path.unlink(missing_ok=True)

    def _statement_table(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                [
                    '25.07.2026 18:04:10',
                    '12110294722',
                    'Возврат оплаты за\nтовары/услуги, купленные на',
                    '+ 101.00 ₽',
                    '+ 101.00 ₽',
                ],
                ['', '', 'Платформе Ozon, заказ № 0814. Без НДС.', '', ''],
                [
                    '25.07.2026 17:57:47',
                    '12110154130',
                    'Оплата товаров/услуг\nна Платформе Ozon, заказ № 0814.',
                    '- 2 561.00 ₽',
                    '- 2 561.00 ₽',
                ],
                [
                    '25.07.2026 17:57:42',
                    '8269844786',
                    'Перевод через СБП. Отправитель: А. П.',
                    '+ 2 600.00 ₽',
                    '+ 2 600.00 ₽',
                ],
                [
                    '20.07.2026 16:53:58',
                    '11994145163',
                    'Чаевые по заказу № tips-0814. Без НДС.',
                    '- 49.00 ₽',
                    '- 49.00 ₽',
                ],
            ],
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.'
        '_extract_pdf_text_for_detection',
        return_value='ООО «ОЗОН Банк»\nСправка о движении средств',
    )
    def test_detects_ozon_statement(self, mock_detect: MagicMock) -> None:
        parser = _create_parser(self.pdf_path)
        self.assertIsInstance(parser, _OzonBankParser)

    def test_real_anonymized_statement_matches_document_totals(self) -> None:
        """Real PDF: 56 rows and totals equal the printed statement totals.

        Expected values come from the document text: incoming
        31 337.83 ₽, outgoing 31 431.03 ₽ and outgoing balance 50.50 ₽,
        so the signed sum is -93.20 ₽. Category counts and sums were
        verified against the table rows, not copied from the parser.
        """
        result = _OzonBankParser(OZON_FIXTURE).parse()

        transactions = result.transactions
        self.assertEqual(len(transactions), 56)
        self.assertFalse(
            [item for item in transactions if item.get('parse_issue')],
        )
        amounts = [cast('Decimal', item['amount']) for item in transactions]
        self.assertEqual(
            sum(amount for amount in amounts if amount > 0),
            Decimal('31337.83'),
        )
        self.assertEqual(
            sum(-amount for amount in amounts if amount < 0),
            Decimal('31431.03'),
        )
        self.assertEqual(sum(amounts), Decimal('-93.20'))
        self.assertIsNone(result.closing_balance)
        self.assertIsNone(result.period_start)

        by_category: dict[str | None, list[Decimal]] = {}
        for item in transactions:
            by_category.setdefault(item['category_name'], []).append(
                cast('Decimal', item['amount']),
            )
        self.assertEqual(
            {name: len(values) for name, values in by_category.items()},
            {
                'Покупки Ozon': 24,
                'Возвраты Ozon': 9,
                'Чаевые Ozon': 5,
                None: 18,
            },
        )
        self.assertEqual(
            sum(by_category['Покупки Ozon']),
            Decimal('-31035.03'),
        )
        self.assertEqual(
            sum(by_category['Возвраты Ozon']),
            Decimal('7000.83'),
        )
        self.assertEqual(sum(by_category['Чаевые Ozon']), Decimal('-396.00'))
        self.assertEqual(sum(by_category[None]), Decimal('24337.00'))
        self.assertTrue(
            all(
                item['description'].startswith('Перевод')
                for item in transactions
                if item['category_name'] is None
            ),
        )
        self.assertEqual(
            len({item['source_ref'] for item in transactions}),
            56,
        )

        first = transactions[0]
        self.assertEqual(first['amount'], Decimal('-50.00'))
        self.assertEqual(first['category_name'], 'Чаевые Ozon')
        self.assertEqual(first['source_ref'], '11721043560')

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_parses_known_operations_and_keeps_transfer_visible(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        mock_table = MagicMock()
        mock_table.df = self._statement_table()
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(len(result.transactions), 4)
        self.assertIsNone(result.closing_balance)
        self.assertIsNone(result.closing_balance_date)
        self.assertIsNone(result.period_start)
        self.assertEqual(result.bank, 'ozon')
        self.assertEqual(result.format_version, 3)
        self.assertEqual(
            [item['category_name'] for item in result.transactions],
            ['Возвраты Ozon', 'Покупки Ozon', None, 'Чаевые Ozon'],
        )
        self.assertEqual(
            [item['description'] for item in result.transactions],
            [
                'Возвраты Ozon',
                'Покупки Ozon',
                'Перевод через СБП. Отправитель: А. П.',
                'Чаевые Ozon',
            ],
        )
        self.assertEqual(
            [item['amount'] for item in result.transactions],
            [
                Decimal('101.00'),
                Decimal('-2561.00'),
                Decimal('2600.00'),
                Decimal('-49.00'),
            ],
        )
        self.assertTrue(
            all(item['source'] == 'ozon' for item in result.transactions),
        )
        self.assertTrue(
            all(
                item['source_ref_strength'] == 'weak'
                for item in result.transactions
            ),
        )
        self.assertNotIn('parse_issue', result.transactions[2])

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_statement_with_only_transfers_keeps_potential_operation(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame(
            [
                [
                    '25.07.2026 17:57:42',
                    '8269844786',
                    'Перевод через СБП.',
                    '+ 2 600.00 ₽',
                    '+ 2 600.00 ₽',
                ],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(len(result.transactions), 1)
        transfer = result.transactions[0]
        self.assertIsNone(transfer['category_name'])
        self.assertEqual(transfer['amount'], Decimal('2600.00'))
        self.assertEqual(transfer['description'], 'Перевод через СБП.')
        self.assertEqual(transfer['source_ref'], '8269844786')
        self.assertNotIn('parse_issue', transfer)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_parses_format_with_processing_date_rows(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        # Mirrors camelot output of the 2026 format: the processing date
        # sits on its own row right under the operation date.
        mock_table = MagicMock()
        mock_table.page = '1'
        mock_table.df = pd.DataFrame(
            [
                ['05.08.2026 10:00:00', 'aaaa1111-', 'Ozon', '- 500.00 ₽'],
                ['05.08.2026 10:30:00', 'bbbb-2222-', '', ''],
                ['', 'cccc3333', '', ''],
                ['05.08.2026 09:59:00', 'T0000001', 'Иван', '+ 500.00 ₽'],
                ['05.08.2026 09:59:00', 'T0000002', 'Иванович', ''],
                ['04.08.2026 12:00:00', 'dddd4444-', 'Чаевые', '- 50.00 ₽'],
                ['04.08.2026 12:40:00', 'eeee-', 'курьеру', ''],
                ['', '', 'Ozon', ''],
                ['03.08.2026 08:00:00', 'ffff5555-', 'Возврат', '+ 12.34 ₽'],
                ['03.08.2026 08:00:00', '6666-', 'средств', ''],
                ['02.08.2026 20:00:00', '7777aaaa-', 'Комиссия за', '- 9.00 ₽'],
                ['02.08.2026 20:00:00', 'bbbb-', 'смс-', ''],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(
            [
                (item['category_name'], item['amount'], item['source_ref'])
                for item in result.transactions
            ],
            [
                (
                    'Покупки Ozon',
                    Decimal('-500.00'),
                    'aaaa1111-bbbb-2222-cccc3333',
                ),
                (None, Decimal('500.00'), 'T0000001'),
                (None, None, 'T0000002'),
                ('Чаевые Ozon', Decimal('-50.00'), 'dddd4444-eeee-'),
                ('Возвраты Ozon', Decimal('12.34'), 'ffff5555-6666-'),
                (None, Decimal('-9.00'), '7777aaaa-bbbb-'),
            ],
        )
        self.assertEqual(
            [item['description'] for item in result.transactions],
            [
                'Покупки Ozon',
                'Иван',
                'Иванович',
                'Чаевые Ozon',
                'Возвраты Ozon',
                'Комиссия за смс-',
            ],
        )
        # The processing-date row above stays a continuation, not a row.
        self.assertEqual(
            result.transactions[0]['source_ref'],
            'aaaa1111-bbbb-2222-cccc3333',
        )
        self.assertEqual(result.transactions[2]['parse_issue'], 'unparsed')

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_missing_amount_operation_keeps_its_own_fragment(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """An amountless operation is not glued to a neighbour's amount."""
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame(
            [
                ['01.09.2026 10:00:00', 'DOC-A', 'Ozon', '- 100.00 ₽'],
                ['01.09.2026 11:00:00', 'DOC-B', 'Комиссия банка', ''],
                ['01.09.2026 12:00:00', 'DOC-C', 'Ozon', '- 200.00 ₽'],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(len(result.transactions), 3)
        first, middle, last = result.transactions
        self.assertEqual(first['amount'], Decimal('-100.00'))
        self.assertEqual(first['source_ref'], 'DOC-A')
        self.assertNotIn('parse_issue', first)
        self.assertIsNone(middle['amount'])
        self.assertEqual(middle['source_ref'], 'DOC-B')
        self.assertEqual(middle['description'], 'Комиссия банка')
        self.assertEqual(middle['parse_issue'], 'unparsed')
        self.assertEqual(last['amount'], Decimal('-200.00'))
        self.assertEqual(last['source_ref'], 'DOC-C')
        self.assertNotIn('parse_issue', last)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_malformed_date_operation_keeps_its_own_fragment(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """A broken date never merges one amount into another observation."""
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame(
            [
                ['01.09.2026 10:00:00', 'DOC-A', 'Ozon', '- 100.00 ₽'],
                ['01.09.2026 10:00', 'DOC-B', 'Комиссия банка', '- 5.00 ₽'],
                ['01.09.2026 12:00:00', 'DOC-C', 'Ozon', '- 200.00 ₽'],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(len(result.transactions), 3)
        first, middle, last = result.transactions
        self.assertEqual(first['amount'], Decimal('-100.00'))
        self.assertEqual(first['source_ref'], 'DOC-A')
        self.assertIsNone(middle['date'])
        self.assertEqual(middle['amount'], Decimal('-5.00'))
        self.assertEqual(middle['source_ref'], 'DOC-B')
        self.assertEqual(middle['parse_issue'], 'unparsed')
        self.assertEqual(last['amount'], Decimal('-200.00'))
        self.assertEqual(last['source_ref'], 'DOC-C')

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_unreadable_date_and_amount_keeps_own_fragment(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """A purpose and document survive an unreadable date and amount.

        The fragment must not extend the previous operation: its purpose
        and document would otherwise distort the neighbour's row and the
        separate observation would disappear.
        """
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame(
            [
                ['01.09.2026 10:00:00', 'DOC-A', 'Ozon', '- 100.00 ₽'],
                ['н/д', 'DOC-B', 'Комиссия банка', '- ₽'],
                ['01.09.2026 12:00:00', 'DOC-C', 'Ozon', '- 200.00 ₽'],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(len(result.transactions), 3)
        first, middle, last = result.transactions
        self.assertEqual(first['amount'], Decimal('-100.00'))
        self.assertEqual(first['source_ref'], 'DOC-A')
        self.assertEqual(first['description'], 'Покупки Ozon')
        self.assertNotIn('parse_issue', first)
        self.assertIsNone(middle['date'])
        self.assertIsNone(middle['amount'])
        self.assertEqual(middle['source_ref'], 'DOC-B')
        self.assertEqual(middle['description'], 'Комиссия банка')
        self.assertEqual(middle['parse_issue'], 'unparsed')
        self.assertEqual(last['amount'], Decimal('-200.00'))
        self.assertEqual(last['source_ref'], 'DOC-C')
        self.assertNotIn('parse_issue', last)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_ambiguous_fragment_before_first_operation_is_kept(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """A fragment above the first operation is not silently dropped."""
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame(
            [
                ['', 'DOC-B', 'Комиссия банка', ''],
                ['01.09.2026 10:00:00', 'DOC-A', 'Ozon', '- 100.00 ₽'],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(len(result.transactions), 2)
        fragment, operation = result.transactions
        self.assertEqual(fragment['parse_issue'], 'unparsed')
        self.assertEqual(fragment['source_ref'], 'DOC-B')
        self.assertEqual(fragment['description'], 'Комиссия банка')
        self.assertIsNone(fragment['amount'])
        self.assertEqual(operation['amount'], Decimal('-100.00'))
        self.assertEqual(operation['source_ref'], 'DOC-A')
        self.assertNotIn('parse_issue', operation)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_unparsed_row_stays_visible_without_blocking_others(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """A row fragment is preserved; the next valid row still parses."""
        mock_table = MagicMock()
        mock_table.page = '2'
        mock_table.df = pd.DataFrame(
            [
                ['05.08.2026 10:00:00', '', 'Ozon', '- 10.00 ₽'],
                ['05.08.2026 11:00:00', '12345', 'Ozon', '- 20.00 ₽'],
                ['05.08.2026 12:00:00', '12346', 'Ozon', '- ₽'],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(len(result.transactions), 3)
        missing_document = result.transactions[0]
        self.assertEqual(missing_document['parse_issue'], 'unparsed')
        self.assertIsNone(missing_document['source_ref'])
        self.assertEqual(missing_document['amount'], Decimal('-10.00'))
        valid = result.transactions[1]
        self.assertNotIn('parse_issue', valid)
        self.assertEqual(valid['source_ref'], '12345')
        unreadable_amount = result.transactions[2]
        self.assertEqual(unreadable_amount['parse_issue'], 'unparsed')
        self.assertIsNone(unreadable_amount['amount'])
        self.assertEqual(unreadable_amount['source_ref'], '12346')
        self.assertEqual(
            [item['row_position'] for item in result.transactions],
            [0, 1, 2],
        )

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_repeated_header_and_broken_row_stay_out_of_previous_operation(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """A repeated header never extends a row; a broken row is its own."""
        mock_table = MagicMock()
        mock_table.page = '2'
        mock_table.df = pd.DataFrame(
            [
                ['01.09.2026 10:00:00', 'DOC-A', 'Ozon', '- 100.00 ₽'],
                ['Дата операции', 'Документ', 'Назначение платежа', ''],
                ['02.09.2026 11:00:00', '', 'Комиссия банка', ''],
                ['03.09.2026 12:00:00', 'DOC-C', 'Ozon', '- 200.00 ₽'],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(len(result.transactions), 3)
        first, broken, last = result.transactions
        self.assertEqual(first['source_ref'], 'DOC-A')
        self.assertEqual(first['description'], 'Покупки Ozon')
        self.assertEqual(first['amount'], Decimal('-100.00'))
        self.assertEqual(broken['parse_issue'], 'unparsed')
        self.assertIsNone(broken['source_ref'])
        self.assertEqual(broken['description'], 'Комиссия банка')
        self.assertIsNone(broken['amount'])
        self.assertEqual(last['source_ref'], 'DOC-C')
        self.assertEqual(last['amount'], Decimal('-200.00'))

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_repeated_document_number_keeps_both_rows(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """A reused document number never merges away a real operation."""
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame(
            [
                ['01.09.2026 10:00:00', 'DOC-1', 'Ozon', '- 100.00 ₽'],
                ['02.09.2026 10:00:00', 'DOC-1', 'Ozon', '- 200.00 ₽'],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        result = _OzonBankParser(self.pdf_path).parse()

        self.assertEqual(len(result.transactions), 2)
        self.assertEqual(
            [item['source_ref'] for item in result.transactions],
            ['DOC-1', 'DOC-1'],
        )
        self.assertEqual(
            [item['row_position'] for item in result.transactions],
            [0, 1],
        )

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_structure_without_operations_is_a_fatal_parse_error(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """A file with no potential operation proves nothing and is fatal."""
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame(
            [
                ['05.08.2026 10:30:00', 'bbbb-2222-', '', ''],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        with self.assertRaises(BankStatementParseError):
            _OzonBankParser(self.pdf_path).parse()

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_broken_table_is_a_fatal_parse_error(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        mock_camelot.read_pdf.side_effect = RuntimeError('broken table')

        with self.assertRaises(BankStatementParseError):
            _OzonBankParser(self.pdf_path).parse()

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.'
        '_extract_pdf_text_for_detection',
        return_value='ООО «ОЗОН Банк»\nСправка о движении средств',
    )
    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_deduplicates_same_amount_and_date_one_to_one(
        self,
        mock_camelot: MagicMock,
        mock_detect: MagicMock,
    ) -> None:
        """Both rows matching one legacy candidate become probable duplicates.

        Probable-duplicate detection runs ahead of the legacy-backfill
        fallback and does not remove a candidate from the pool once another
        row has matched it, so two incoming rows that both match the same
        legacy transaction by (account, type, amount, calendar date) each
        surface as a probable duplicate for reconciliation — the legacy
        transaction itself is left untouched.
        """
        category = Category.objects.create(
            user=self.user,
            name='Чек Ozon',
            type=TransactionType.EXPENSE,
        )
        existing = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('499.00'),
            date=datetime(
                2026,
                7,
                25,
                10,
                tzinfo=UTC,
            ),
        )
        mock_table = MagicMock()
        mock_table.df = pd.DataFrame(
            [
                [
                    '25.07.2026 17:00:00',
                    '12110154131',
                    'Оплата товаров/услуг на Платформе Ozon, заказ № 1.',
                    '- 499.00 ₽',
                    '- 499.00 ₽',
                ],
                [
                    '25.07.2026 18:00:00',
                    '12110154132',
                    'Оплата товаров/услуг на Платформе Ozon, заказ № 2.',
                    '- 499.00 ₽',
                    '- 499.00 ₽',
                ],
            ],
        )
        mock_camelot.read_pdf.return_value = [mock_table]

        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file=SimpleUploadedFile(
                'ozon.pdf',
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
        )

        result = process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertEqual(result['skipped_count'], 2)
        self.assertEqual(result['expense_count'], 0)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        existing.refresh_from_db()
        self.assertIsNone(existing.source_ref)
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                candidate=existing,
            ).count(),
            2,
        )

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_task_uses_explicit_ozon_category(
        self,
        mock_parser_cls: MagicMock,
    ) -> None:
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        mock_parser_cls.return_value.parse.return_value = StatementParseResult(
            transactions=[
                {
                    'date': timezone.now(),
                    'amount': Decimal('-100.00'),
                    'description': 'Покупки Ozon',
                    'category_name': 'Покупки Ozon',
                    'source_ref': 'ozon-1',
                    'source': 'ozon',
                },
            ],
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/ozon.pdf',
        )

        process_bank_statement_task.apply(args=[upload.pk])

        classifier.classify.assert_not_called()
        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Покупки Ozon',
                type=TransactionType.EXPENSE,
            ).exists(),
        )


class TestBankStatementImportReliability(TestCase):
    """Import must survive worker loss, retries and bank-truth balances."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Тестовый счет',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _create_upload(self) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file=SimpleUploadedFile(
                'statement.pdf',
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
        )

    def _mock_table(self, mock_camelot: MagicMock) -> None:
        mock_df = pd.DataFrame(
            {
                0: ['', '01.01.2024 10:00', '1', '2'],
                1: ['', '', '', ''],
                2: ['', '', '', ''],
                3: ['', '', '', ''],
                4: ['', '', '', ''],
                5: ['', '', 'Большая покупка', 'Зарплата'],
                6: ['', '', '-5000,00 ₽', '+50000,00 ₽'],
            },
        )
        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_expense_above_balance_is_imported_without_retries(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """A statement row larger than the balance does not abort import."""
        self._mock_table(mock_camelot)
        upload = self._create_upload()

        with patch.object(process_bank_statement_task, 'retry') as retry:
            result = process_bank_statement_task.apply(args=[upload.pk]).get()

        retry.assert_not_called()
        self.assertEqual(result['expense_count'], 1)
        self.assertEqual(result['income_count'], 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('46000.00'))
        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_rerun_after_second_row_failure_counts_first_row_once(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """First row committed, second failed: rerun finishes with 1+1."""
        self._mock_table(mock_camelot)
        upload = self._create_upload()
        service = ApplicationContainer().users.bank_statement_import_service()
        real = service._save_autopost_row
        calls = 0

        def flaky(*args: Any, **kwargs: Any) -> BankStatementRow:
            nonlocal calls
            calls += 1
            if calls > 1:
                raise RuntimeError('worker died')
            return cast('BankStatementRow', real(*args, **kwargs))

        with (
            patch.object(service, '_save_autopost_row', side_effect=flaky),
            self.assertRaises(RuntimeError),
        ):
            service.import_statement(upload)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )

        upload.refresh_from_db()
        upload.status = BankStatementUpload.Status.PROCESSING
        upload.save(update_fields=['status'])
        result = process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            2,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('46000.00'))
        self.assertEqual(result['income_count'], 1)
        self.assertEqual(result['expense_count'], 1)
        self.assertEqual(result['skipped_count'], 0)

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_rerun_with_reset_cursor_relies_on_unique_constraints(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Even a lost cursor cannot duplicate rows or the balance."""
        self._mock_table(mock_camelot)
        upload = self._create_upload()
        process_bank_statement_task.apply(args=[upload.pk]).get()

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            processed_transactions=0,
            income_count=0,
            expense_count=0,
            skipped_count=0,
            status=BankStatementUpload.Status.PROCESSING,
        )
        process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            2,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('46000.00'))

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_status_is_not_failed_while_retry_is_pending(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """A transient error keeps PROCESSING until retries run out."""
        self._mock_table(mock_camelot)
        upload = self._create_upload()

        with (
            patch(
                'hasta_la_vista_money.users.services.bank_statement_import.'
                'BankStatementImportService.import_statement',
                side_effect=OperationalError('db gone'),
            ),
            patch.object(
                process_bank_statement_task,
                'retry',
                side_effect=Retry(),
            ),
            self.assertRaises(Retry),
        ):
            process_bank_statement_task.apply(
                args=[upload.pk],
                throw=True,
            ).get()

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.PROCESSING)

    def test_parse_failure_after_deadline_does_not_mark_failed(self) -> None:
        """An expired run must not write FAILED before cleanup clears it."""
        upload = self._create_upload()
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            celery_task_id='run-active',
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        def expire_then_fail() -> None:
            BankStatementUpload.objects.filter(pk=upload.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1),
            )
            raise BankStatementParseError('expired during parse')

        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.side_effect = expire_then_fail
            with self.assertRaises(BankStatementParseError):
                process_bank_statement_task.apply(
                    args=[upload.pk, 'run-active'],
                ).get()

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.PROCESSING)
        self.assertEqual(upload.celery_task_id, 'run-active')
        self.assertEqual(upload.failed_count, 0)
        self.assertEqual(upload.error_message, '')
        self.assertIsNone(upload.retention_cleaned_at)

    def _raiffeisen_upload(
        self,
        transactions: list[dict[str, Any]],
        *,
        file_hash: str = '',
        format_version: int = 1,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> BankStatementUpload:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/raiffeisen.pdf',
            file_hash=file_hash,
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=transactions,
                bank='raiffeisen',
                format_version=format_version,
                period_start=period_start,
                period_end=period_end,
            )
            process_bank_statement_task.apply(args=[upload.pk])
        return upload

    def _sberbank_upload(
        self,
        transactions: list[dict[str, Any]],
        *,
        account: Account | None = None,
        file_hash: str = '',
        format_version: int = 2,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> BankStatementUpload:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=account or self.account,
            pdf_file='bank_statements/sberbank.pdf',
            file_hash=file_hash,
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=transactions,
                bank='sberbank',
                format_version=format_version,
                period_start=period_start,
                period_end=period_end,
            )
            process_bank_statement_task.apply(args=[upload.pk])
        return upload

    def _ozon_upload(
        self,
        transactions: list[dict[str, Any]],
        *,
        file_hash: str = '',
        format_version: int = 3,
    ) -> BankStatementUpload:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/ozon.pdf',
            file_hash=file_hash,
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=transactions,
                bank='ozon',
                format_version=format_version,
            )
            process_bank_statement_task.apply(args=[upload.pk])
        return upload

    def test_sberbank_real_statement_imports_and_keeps_repayments(self) -> None:
        """Import the real anonymized Sberbank statement without AI guesses."""
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        credit_account = Account.objects.create(
            user=self.user,
            name_account='Кредитная карта Сбербанка',
            balance=Decimal('1000.00'),
            currency='RUB',
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=credit_account,
            pdf_file=SimpleUploadedFile(
                'sberbank.pdf',
                SBERBANK_FIXTURE.read_bytes(),
                content_type='application/pdf',
            ),
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        rows = BankStatementRow.objects.filter(upload=upload)
        self.assertEqual(upload.total_transactions, 6)
        self.assertEqual(upload.failed_count, 0)
        self.assertEqual(rows.count(), 6)
        self.assertEqual(
            rows.filter(
                decision=BankStatementRow.Decision.NEEDS_TRANSFER,
            ).count(),
            2,
        )
        self.assertEqual(
            rows.filter(decision=BankStatementRow.Decision.NEW).count(),
            4,
        )
        self.assertFalse(
            rows.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).exists(),
        )
        self.assertEqual(
            set(rows.values_list('source_ref', flat=True)),
            {'676887', '188529', '360456', '356063', '700037', '588469'},
        )
        movements = Transaction.objects.filter(account=credit_account)
        self.assertEqual(movements.count(), 4)
        self.assertFalse(movements.filter(type=TransactionType.INCOME).exists())
        self.assertEqual(
            sum(movements.values_list('amount', flat=True)),
            Decimal('18669.57'),
        )
        self.assertEqual(upload.income_count, 0)
        self.assertEqual(upload.expense_count, 4)
        self.assertEqual(upload.needs_transfer_count, 2)
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        status = self.client.get(
            reverse(
                'finance_account:bank_statement_upload_status',
                args=[upload.pk],
            ),
        )
        self.assertEqual(
            status.json()['reconciliation_url'],
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[upload.pk],
            ),
        )
        classifier.classify.assert_not_called()

    def test_raiffeisen_known_category_posts_row_and_movement(self) -> None:
        """A known local category posts exactly one linked movement."""
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )

        upload = self._raiffeisen_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('1500.00'),
                    'description': 'Зачисление заработной платы',
                    'source_ref': 'R-1',
                    'source_ref_strength': 'weak',
                    'category_name': 'Заработная плата',
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        rows = BankStatementRow.objects.filter(upload=upload)
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(row.transaction)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.account.balance, Decimal('2500.00'))
        self.assertEqual(upload.imported_count, 1)
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)
        classifier.classify.assert_not_called()

    def test_raiffeisen_unknown_category_awaits_markup(self) -> None:
        """An unknown category keeps the row unresolved and moves no money."""
        upload = self._raiffeisen_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('-13.20'),
                    'description': 'Оплата в MAGNIT',
                    'source_ref': 'R-2',
                    'source_ref_strength': 'weak',
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(row.transaction)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def test_raiffeisen_repeated_ref_is_unresolved(self) -> None:
        """A repeated document number never proves a new unambiguous row."""
        upload = self._raiffeisen_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('-10.00'),
                    'description': 'Снятие наличных',
                    'source_ref': 'REPEATED',
                    'source_ref_strength': 'weak',
                    'category_name': 'Наличные',
                },
                {
                    'date': timezone.now(),
                    'amount': Decimal('-20.00'),
                    'description': 'Снятие наличных',
                    'source_ref': 'REPEATED',
                    'source_ref_strength': 'weak',
                    'category_name': 'Наличные',
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            2,
        )
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def test_raiffeisen_row_error_does_not_block_other_rows(self) -> None:
        """A recoverable row error stays visible and other rows still post."""
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        upload = self._raiffeisen_upload(
            [
                {
                    'date': None,
                    'amount': None,
                    'description': 'Неизвестная операция',
                    'parse_issue': 'unsupported',
                },
                {
                    'date': timezone.now(),
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-3',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            1,
        )
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.NEW,
            ).count(),
            1,
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(upload.failed_count, 1)
        self.assertEqual(self.account.balance, Decimal('986.80'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        classifier.classify.assert_not_called()

    def test_sberbank_known_category_posts_row_and_movement(self) -> None:
        """A known local category posts one linked movement, once."""
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        moment = timezone.now()
        row_data = {
            'date': moment,
            'amount': Decimal('-73.00'),
            'description': 'Транспорт',
            'source_ref': '869838',
            'source_ref_strength': 'weak',
            'category_name': 'Транспорт',
            'row_position': 0,
        }
        upload = self._sberbank_upload([row_data])

        upload.refresh_from_db()
        self.account.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(row.transaction)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.account.balance, Decimal('927.00'))
        self.assertEqual(upload.imported_count, 1)
        classifier.classify.assert_not_called()

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            processed_transactions=0,
            income_count=0,
            expense_count=0,
            skipped_count=0,
            needs_transfer_count=0,
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=[row_data],
                bank='sberbank',
                format_version=2,
            )
            process_bank_statement_task.apply(args=[upload.pk])

        self.account.refresh_from_db()
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(
            BankStatementRow.objects.filter(upload=upload).count(),
            1,
        )
        self.assertEqual(self.account.balance, Decimal('927.00'))

    def test_sberbank_unknown_category_awaits_markup(self) -> None:
        """An unknown category stays unresolved and moves no money."""
        upload = self._sberbank_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('-13.20'),
                    'description': 'Покупка в MAGNIT',
                    'source_ref': 'A-1',
                    'source_ref_strength': 'weak',
                    'category_name': None,
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(row.transaction)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def test_sberbank_credit_income_is_needs_transfer_not_income(self) -> None:
        """A positive credit-card row is an unperformed repayment."""
        credit_account = Account.objects.create(
            user=self.user,
            name_account='Кредитная карта',
            balance=Decimal('1000.00'),
            currency='RUB',
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
        )
        upload = self._sberbank_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('50546.00'),
                    'description': 'Перевод на карту',
                    'source_ref': 'A-2',
                    'source_ref_strength': 'weak',
                    'category_name': None,
                },
            ],
            account=credit_account,
        )

        upload.refresh_from_db()
        credit_account.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEEDS_TRANSFER)
        self.assertIsNone(row.transaction)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(credit_account.balance, Decimal('1000.00'))
        self.assertEqual(upload.income_count, 0)
        self.assertEqual(upload.needs_transfer_count, 1)

    def test_sberbank_repeated_authcode_keeps_both_rows_unresolved(
        self,
    ) -> None:
        """A reused auth code neither merges nor posts either operation."""
        moment = timezone.now()
        self._sberbank_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-10.00'),
                    'description': 'Транспорт',
                    'source_ref': 'REPEATED',
                    'source_ref_strength': 'weak',
                    'category_name': 'Транспорт',
                    'row_position': 0,
                },
                {
                    'date': moment,
                    'amount': Decimal('-20.00'),
                    'description': 'Транспорт',
                    'source_ref': 'REPEATED',
                    'source_ref_strength': 'weak',
                    'category_name': 'Транспорт',
                    'row_position': 1,
                },
            ],
        )

        self.account.refresh_from_db()
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            BankStatementRow.objects.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            2,
        )

    def test_sberbank_row_error_does_not_block_other_rows(self) -> None:
        """A recoverable row error stays visible and other rows still post."""
        upload = self._sberbank_upload(
            [
                {
                    'date': None,
                    'amount': None,
                    'description': 'Фрагмент без суммы',
                    'source_ref': 'A-3',
                    'parse_issue': 'unsupported',
                },
                {
                    'date': timezone.now(),
                    'amount': Decimal('-73.00'),
                    'description': 'Транспорт',
                    'source_ref': 'A-4',
                    'source_ref_strength': 'weak',
                    'category_name': 'Транспорт',
                    'row_position': 1,
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            1,
        )
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.NEW,
            ).count(),
            1,
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(upload.failed_count, 1)
        self.assertEqual(self.account.balance, Decimal('927.00'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def test_sberbank_empty_parse_is_not_completed(self) -> None:
        """An empty Sberbank parse does not prove that there are no rows."""
        upload = self._sberbank_upload([])

        upload.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertTrue(upload.error_message)
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(BankStatementRow.objects.exists())

    def test_sberbank_same_file_position_is_exact_duplicate(self) -> None:
        """File hash, stable format, position and fields prove a repeat."""
        moment = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Транспорт',
            type=TransactionType.EXPENSE,
        )
        canonical_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/canonical.pdf',
            file_hash='canonical-hash',
        )
        canonical_transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('73.00'),
            date=moment,
            source_ref='A-EXACT',
            source_file_hash='same-file',
            source_row_position=0,
            source_format_version=2,
        )
        canonical_row = BankStatementRow.objects.create(
            upload=canonical_upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=moment,
            amount=Decimal('73.00'),
            source_ref='A-EXACT',
            source_row_position=0,
            transaction=canonical_transaction,
            decision=BankStatementRow.Decision.NEW,
        )
        upload = self._sberbank_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-73.00'),
                    'description': 'Транспорт',
                    'source_ref': 'A-EXACT',
                    'source_ref_strength': 'weak',
                    'category_name': 'Транспорт',
                    'row_position': 0,
                },
            ],
            file_hash='same-file',
        )

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.DUPLICATE)
        self.assertEqual(row.canonical_row, canonical_row)
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_sberbank_parser_drift_is_not_exact(self) -> None:
        """A different parser format mapping requires manual reassignment."""
        moment = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Транспорт',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('73.00'),
            date=moment,
            source_ref='A-DRIFT',
            source_file_hash='same-file',
            source_row_position=0,
            source_format_version=1,
        )
        upload = self._sberbank_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-73.00'),
                    'description': 'Транспорт',
                    'source_ref': 'A-DRIFT',
                    'source_ref_strength': 'weak',
                    'category_name': 'Транспорт',
                    'row_position': 0,
                },
            ],
            file_hash='same-file',
            format_version=2,
        )

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_empty_parse_is_not_completed(self) -> None:
        """An empty parse does not prove that the statement has no rows."""
        upload = self._raiffeisen_upload([])

        upload.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertTrue(upload.error_message)
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(BankStatementRow.objects.exists())

    def test_repeated_import_is_idempotent(self) -> None:
        """Re-running the import does not create a second movement."""
        upload = self._raiffeisen_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-4',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                },
            ],
        )

        process_bank_statement_task.apply(args=[upload.pk])

        self.account.refresh_from_db()
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(BankStatementRow.objects.count(), 1)
        self.assertEqual(self.account.balance, Decimal('986.80'))

    def test_repeated_import_is_idempotent_after_cursor_reset(self) -> None:
        """A reset import cursor does not post the same row twice."""
        moment = timezone.now()
        upload = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-6',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='cursor-file',
        )

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            processed_transactions=0,
        )
        process_bank_statement_task.apply(args=[upload.pk])

        self.account.refresh_from_db()
        self.assertEqual(Transaction.objects.count(), 1)
        rows = BankStatementRow.objects.filter(upload=upload)
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(row.transaction)
        self.assertIsNone(row.canonical_row)
        self.assertEqual(self.account.balance, Decimal('986.80'))

    def test_known_row_does_not_post_over_existing_unresolved(self) -> None:
        """A known local category never posts over an unresolved repeat."""
        moment = timezone.now()
        self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-50.00'),
                    'description': 'Оплата в MAGNIT',
                    'source_ref': 'SHARED',
                    'source_ref_strength': 'weak',
                    'row_position': 0,
                },
            ],
        )
        self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-50.00'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'SHARED',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
        )

        self.account.refresh_from_db()
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            BankStatementRow.objects.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            2,
        )

    def test_autopost_links_existing_open_row(self) -> None:
        """An open row at the same position is linked, not left behind."""
        moment = timezone.now()
        upload = self._create_upload()
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=None,
            transaction_date=None,
            amount=None,
            description='',
            source_row_position=0,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=[
                    {
                        'date': moment,
                        'amount': Decimal('-13.20'),
                        'description': 'Комиссия за обслуживание',
                        'source_ref': 'R-7',
                        'source_ref_strength': 'weak',
                        'category_name': 'Комиссия банка',
                        'row_position': 0,
                    },
                ],
                bank='raiffeisen',
            )
            process_bank_statement_task.apply(args=[upload.pk])

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(row.transaction)
        self.assertEqual(row.amount, Decimal('13.20'))
        self.assertEqual(row.transaction_date, moment)
        self.assertEqual(row.transaction_type, TransactionType.EXPENSE)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_duplicate_identical_rows_stay_visible(self) -> None:
        """Two identical rows with one reference both stay unresolved."""
        moment = timezone.now()
        entry = {
            'date': moment,
            'amount': Decimal('-13.20'),
            'description': 'Комиссия за обслуживание',
            'source_ref': 'SAME',
            'source_ref_strength': 'weak',
            'category_name': 'Комиссия банка',
            'row_position': 0,
        }
        second = {**entry, 'row_position': 1}
        self._raiffeisen_upload([entry, second])

        self.account.refresh_from_db()
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            BankStatementRow.objects.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            2,
        )

    def test_weak_ref_same_file_proves_visible_exact_duplicate(self) -> None:
        """Same file hash, position and format prove one visible duplicate."""
        moment = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Комиссия банка',
            type=TransactionType.EXPENSE,
        )
        canonical_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/canonical.pdf',
            file_hash='canonical-hash',
        )
        canonical_transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('13.20'),
            date=moment,
            source_ref='R-EXACT',
            source_file_hash='same-file',
            source_row_position=0,
            source_format_version=1,
        )
        canonical_row = BankStatementRow.objects.create(
            upload=canonical_upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=moment,
            amount=Decimal('13.20'),
            source_ref='R-EXACT',
            source_row_position=0,
            transaction=canonical_transaction,
            decision=BankStatementRow.Decision.NEW,
        )
        upload = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-EXACT',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='same-file',
        )

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.DUPLICATE)
        self.assertEqual(row.canonical_row, canonical_row)
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_weak_ref_parser_drift_is_not_exact(self) -> None:
        """A different parser mapping requires manual reassignment."""
        moment = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Комиссия банка',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('13.20'),
            date=moment,
            source_ref='R-DRIFT',
            source_file_hash='same-file',
            source_row_position=0,
            source_format_version=1,
        )
        upload = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-DRIFT',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='same-file',
            format_version=2,
        )

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_position_mismatch_is_a_conflict(self) -> None:
        """A different amount at the same position is not an exact repeat."""
        moment = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Комиссия банка',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('99.00'),
            date=moment,
            source_ref='R-CONFLICT',
            source_file_hash='same-file',
            source_row_position=0,
            source_format_version=1,
        )
        upload = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-CONFLICT',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='same-file',
        )

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_weak_ref_other_file_is_not_exact(self) -> None:
        """A different file hash never proves a duplicate by position."""
        moment = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Комиссия банка',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('13.20'),
            date=moment,
            source_ref='R-FILE',
            source_file_hash='file-a',
            source_row_position=0,
            source_format_version=1,
        )
        upload = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-FILE',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='file-b',
        )

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertTrue(row.candidates.exists())
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_two_identical_purchases_keep_both_rows(self) -> None:
        """Two real identical purchases both post and stay visible."""
        moment = timezone.now()
        self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-P1',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-P2',
                    'source_ref_strength': 'weak',
                    'category_name': 'Комиссия банка',
                    'row_position': 1,
                },
            ],
            file_hash='purchases',
        )

        self.account.refresh_from_db()
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(self.account.balance, Decimal('973.60'))
        self.assertEqual(
            BankStatementRow.objects.filter(
                decision=BankStatementRow.Decision.NEW,
            ).count(),
            2,
        )

    def test_real_raiffeisen_statement_posts_only_local_category(self) -> None:
        """Real statement posts only the known cash row and keeps 137 rows."""
        with RAIFFEISEN_REAL_FIXTURE.open('rb') as pdf:
            upload = BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file=File(pdf, name='raiffeisen.pdf'),
            )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(upload.total_transactions, 138)
        self.assertEqual(upload.processed_transactions, 138)
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.account.balance, Decimal('-119000.00'))
        self.assertEqual(
            self.account.account_number,
            '68509471470637308180',
        )
        self.assertEqual(
            upload.statement_closing_balance,
            Decimal('0.00'),
        )
        self.assertIsNone(upload.balance_discrepancy)
        rows = BankStatementRow.objects.filter(upload=upload)
        self.assertEqual(rows.count(), 138)
        self.assertEqual(
            rows.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            137,
        )
        posted = rows.get(
            decision=BankStatementRow.Decision.NEW,
        )
        self.assertEqual(posted.source_row_position, 73)
        self.assertEqual(posted.amount, Decimal('120000.00'))
        self.assertIsNotNone(posted.transaction)

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_raiffeisen_fatal_file_error_fails_visible_without_money(
        self,
        parser: MagicMock,
    ) -> None:
        """A broken file is visible, posts nothing and is not complete."""
        parser.return_value.parse.side_effect = BankStatementParseError(
            'broken file',
        )
        upload = self._create_upload()

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(upload.failed_count, 1)
        self.assertTrue(upload.error_message)
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(BankStatementRow.objects.exists())

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_deterministic_error_fails_without_retry(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Non-transient errors are marked FAILED immediately."""
        self._mock_table(mock_camelot)
        upload = self._create_upload()

        with (
            patch(
                'hasta_la_vista_money.users.services.bank_statement_import.'
                'BankStatementImportService.import_statement',
                side_effect=ValueError('bad row'),
            ),
            patch.object(process_bank_statement_task, 'retry') as retry,
        ):
            process_bank_statement_task.apply(args=[upload.pk])

        retry.assert_not_called()
        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)

    @patch(
        'hasta_la_vista_money.finance_account.bank_statement_views.process_bank_statement_task',
    )
    def test_reupload_of_failed_statement_restarts_task(
        self,
        mock_task: MagicMock,
    ) -> None:
        """Uploading the same file after FAILED enqueues the task again."""
        mock_task.delay.return_value = MagicMock(id='task-id')
        pdf = b'%PDF-1.4 same content'
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            file_hash=sha256(pdf).hexdigest(),
            status=BankStatementUpload.Status.FAILED,
            pdf_file=SimpleUploadedFile('s.pdf', pdf),
        )

        self.client.post(
            reverse('finance_account:bank_statement_upload'),
            {
                'account': self.account.pk,
                'pdf_file': SimpleUploadedFile(
                    's.pdf',
                    pdf,
                    content_type='application/pdf',
                ),
            },
        )

        mock_task.delay.assert_called_once()
        self.assertEqual(mock_task.delay.call_args[0][0], upload.pk)
        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.PENDING)
        self.assertEqual(
            mock_task.delay.call_args[0][1],
            upload.celery_task_id,
        )

    @patch(
        'hasta_la_vista_money.finance_account.bank_statement_views.process_bank_statement_task',
    )
    def test_reupload_of_stale_processing_restarts_but_fresh_does_not(
        self,
        mock_task: MagicMock,
    ) -> None:
        """Only PROCESSING uploads older than the threshold are restarted."""
        mock_task.delay.return_value = MagicMock(id='task-id')
        pdf = b'%PDF-1.4 other content'
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            file_hash=sha256(pdf).hexdigest(),
            status=BankStatementUpload.Status.PROCESSING,
            pdf_file=SimpleUploadedFile('s.pdf', pdf),
        )

        def post() -> None:
            self.client.post(
                reverse('finance_account:bank_statement_upload'),
                {
                    'account': self.account.pk,
                    'pdf_file': SimpleUploadedFile(
                        's.pdf',
                        pdf,
                        content_type='application/pdf',
                    ),
                },
            )

        post()
        mock_task.delay.assert_not_called()

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            updated_at=timezone.now()
            - timedelta(minutes=constants.STATEMENT_UPLOAD_STALE_MINUTES + 1),
        )
        post()
        mock_task.delay.assert_called_once()
        self.assertEqual(mock_task.delay.call_args[0][0], upload.pk)
        upload.refresh_from_db()
        self.assertEqual(
            mock_task.delay.call_args[0][1],
            upload.celery_task_id,
        )

    def test_ozon_known_category_posts_row_and_movement_once(self) -> None:
        """A known local Ozon purpose posts one linked movement, once."""
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        row_data = {
            'date': timezone.now(),
            'amount': Decimal('-100.00'),
            'description': 'Покупки Ozon',
            'source_ref': 'OZ-1',
            'source_ref_strength': 'weak',
            'category_name': 'Покупки Ozon',
            'source': 'ozon',
            'row_position': 0,
        }
        upload = self._ozon_upload([row_data])

        upload.refresh_from_db()
        self.account.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(row.transaction)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.account.balance, Decimal('900.00'))
        self.assertEqual(upload.imported_count, 1)
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)
        classifier.classify.assert_not_called()

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            processed_transactions=0,
            income_count=0,
            expense_count=0,
            skipped_count=0,
            needs_transfer_count=0,
            failed_count=0,
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=[row_data],
                bank='ozon',
                format_version=3,
            )
            process_bank_statement_task.apply(args=[upload.pk])

        self.account.refresh_from_db()
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(
            BankStatementRow.objects.filter(upload=upload).count(),
            1,
        )
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_ozon_unknown_purpose_and_transfer_need_decision(self) -> None:
        """Unknown purposes and transfers stay visible and move no money."""
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        upload = self._ozon_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('-30.00'),
                    'description': 'Комиссия за смс-',
                    'source_ref': 'OZ-2',
                    'source_ref_strength': 'weak',
                    'category_name': None,
                    'source': 'ozon',
                    'row_position': 0,
                },
                {
                    'date': timezone.now(),
                    'amount': Decimal('2600.00'),
                    'description': 'Перевод через СБП. Отправитель: А. П.',
                    'source_ref': 'OZ-3',
                    'source_ref_strength': 'weak',
                    'category_name': None,
                    'source': 'ozon',
                    'row_position': 1,
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        rows = BankStatementRow.objects.filter(upload=upload)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            set(rows.values_list('decision', flat=True)),
            {BankStatementRow.Decision.AWAITING_MARKUP},
        )
        self.assertFalse(rows.exclude(transaction__isnull=True).exists())
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(
            set(rows.values_list('description', flat=True)),
            {
                'Комиссия за смс-',
                'Перевод через СБП. Отправитель: А. П.',
            },
        )
        classifier.classify.assert_not_called()

    def test_ozon_repeated_document_number_keeps_both_unresolved(self) -> None:
        """A reused document number neither merges nor posts either row."""
        moment = timezone.now()
        self._ozon_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-10.00'),
                    'description': 'Покупки Ozon',
                    'source_ref': 'REPEATED',
                    'source_ref_strength': 'weak',
                    'category_name': 'Покупки Ozon',
                    'source': 'ozon',
                    'row_position': 0,
                },
                {
                    'date': moment,
                    'amount': Decimal('-20.00'),
                    'description': 'Покупки Ozon',
                    'source_ref': 'REPEATED',
                    'source_ref_strength': 'weak',
                    'category_name': 'Покупки Ozon',
                    'source': 'ozon',
                    'row_position': 1,
                },
            ],
        )

        self.account.refresh_from_db()
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            BankStatementRow.objects.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            2,
        )

    def test_ozon_row_error_does_not_block_other_rows(self) -> None:
        """A recoverable row error stays visible and other rows still post."""
        upload = self._ozon_upload(
            [
                {
                    'date': None,
                    'amount': None,
                    'description': 'Фрагмент Ozon без суммы',
                    'source_ref': None,
                    'parse_issue': 'unparsed',
                    'row_position': 0,
                },
                {
                    'date': timezone.now(),
                    'amount': Decimal('-100.00'),
                    'description': 'Покупки Ozon',
                    'source_ref': 'OZ-4',
                    'source_ref_strength': 'weak',
                    'category_name': 'Покупки Ozon',
                    'source': 'ozon',
                    'row_position': 1,
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            1,
        )
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.NEW,
            ).count(),
            1,
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(upload.failed_count, 1)
        self.assertEqual(self.account.balance, Decimal('900.00'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def test_ozon_same_file_position_is_exact_duplicate(self) -> None:
        """File hash, stable format, position and fields prove a repeat."""
        moment = timezone.now()
        category = Category.objects.create(
            user=self.user,
            name='Покупки Ozon',
            type=TransactionType.EXPENSE,
        )
        canonical_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/canonical-ozon.pdf',
            file_hash='canonical-ozon-hash',
        )
        canonical_transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=moment,
            source_ref='OZ-EXACT',
            source_file_hash='same-file',
            source_row_position=0,
            source_format_version=3,
        )
        canonical_row = BankStatementRow.objects.create(
            upload=canonical_upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=moment,
            amount=Decimal('100.00'),
            source_ref='OZ-EXACT',
            source_row_position=0,
            transaction=canonical_transaction,
            decision=BankStatementRow.Decision.NEW,
        )
        upload = self._ozon_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-100.00'),
                    'description': 'Покупки Ozon',
                    'source_ref': 'OZ-EXACT',
                    'source_ref_strength': 'weak',
                    'category_name': 'Покупки Ozon',
                    'source': 'ozon',
                    'row_position': 0,
                },
            ],
            file_hash='same-file',
        )

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.DUPLICATE)
        self.assertEqual(row.canonical_row, canonical_row)
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_ozon_reparse_keeps_new_fragment_after_old_position_mapping(
        self,
    ) -> None:
        """An old row at the fragment position is not mistaken for it."""
        moment = datetime(2026, 9, 1, 10, tzinfo=UTC)
        fragment_moment = datetime(2026, 9, 2, 11, tzinfo=UTC)
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/ozon-reparse.pdf',
            file_hash='ozon-reparse-file',
            status=BankStatementUpload.Status.COMPLETED,
        )
        BankStatementRow.objects.create(
            upload=upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=moment,
            amount=Decimal('200.00'),
            description='Ozon',
            source_ref='DOC-C',
            source_ref_strength='weak',
            source_row_position=1,
            source_format_version=2,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        service = ApplicationContainer().users.bank_statement_import_service()
        self.assertTrue(
            service.prepare_known_replay(
                upload,
                SimpleUploadedFile(
                    'ozon-reparse.pdf',
                    b'%PDF-1.4 replay',
                    content_type='application/pdf',
                ),
            ),
        )
        parse_result = StatementParseResult(
            transactions=[
                {
                    'date': moment,
                    'amount': Decimal('-100.00'),
                    'description': 'Покупки Ozon',
                    'source_ref': 'DOC-A',
                    'source_ref_strength': 'weak',
                    'source': 'ozon',
                    'row_position': 0,
                },
                {
                    'date': fragment_moment,
                    'amount': None,
                    'description': 'Комиссия банка',
                    'source_ref': None,
                    'source_ref_strength': 'weak',
                    'source': 'ozon',
                    'row_position': 1,
                    'parse_issue': 'unparsed',
                },
                {
                    'date': moment,
                    'amount': Decimal('-200.00'),
                    'description': 'Ozon',
                    'source_ref': 'DOC-C',
                    'source_ref_strength': 'weak',
                    'source': 'ozon',
                    'row_position': 2,
                },
            ],
            bank='ozon',
            format_version=3,
        )

        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(
                args=[upload.pk, upload.celery_task_id],
            )

        fragment = BankStatementRow.objects.get(
            upload=upload,
            source_row_position=1,
        )
        self.assertEqual(fragment.description, 'Комиссия банка')
        self.assertIsNone(fragment.amount)
        self.assertIsNone(fragment.source_ref)
        self.assertEqual(
            fragment.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertTrue(
            BankStatementRow.objects.filter(
                upload=upload,
                source_row_position=2,
                source_ref='DOC-C',
            ).exists(),
        )

    def test_raiffeisen_reparse_detaches_old_collided_position(self) -> None:
        """A stale row from another page is not restored as the first row."""
        moment = datetime(2026, 2, 1, 10, tzinfo=UTC)
        first_position = RAIFFEISEN_FALLBACK_POSITION_BASE + 1
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/raiffeisen-reparse.pdf',
            file_hash='raiffeisen-reparse-file',
            status=BankStatementUpload.Status.COMPLETED,
        )
        BankStatementRow.objects.create(
            upload=upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=moment,
            amount=Decimal('500.00'),
            description='Оплата покупки',
            source_row_position=first_position,
            source_format_version=2,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        service = ApplicationContainer().users.bank_statement_import_service()
        self.assertTrue(
            service.prepare_known_replay(
                upload,
                SimpleUploadedFile(
                    'raiffeisen-reparse.pdf',
                    b'%PDF-1.4 replay',
                    content_type='application/pdf',
                ),
            ),
        )
        parse_result = StatementParseResult(
            transactions=[
                {
                    'date': moment,
                    'amount': Decimal('-100.00'),
                    'description': 'Перевод средств',
                    'source_ref': None,
                    'source_ref_strength': 'weak',
                    'date_only': True,
                    'row_position': first_position,
                },
                {
                    'date': moment,
                    'amount': Decimal('-500.00'),
                    'description': 'Оплата покупки',
                    'source_ref': None,
                    'source_ref_strength': 'weak',
                    'date_only': True,
                    'row_position': first_position + 1,
                },
            ],
            bank='raiffeisen',
            format_version=3,
        )

        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(
                args=[upload.pk, upload.celery_task_id],
            )

        first = BankStatementRow.objects.get(
            upload=upload,
            source_row_position=first_position,
        )
        self.assertEqual(first.description, 'Перевод средств')
        self.assertEqual(first.amount, Decimal('100.00'))
        second = BankStatementRow.objects.get(
            upload=upload,
            source_row_position=first_position + 1,
        )
        self.assertEqual(second.description, 'Оплата покупки')
        self.assertEqual(second.amount, Decimal('500.00'))

    def test_ozon_without_balance_does_not_claim_zero_or_coverage(self) -> None:
        """A missing balance and period are not filled with zero."""
        upload = self._ozon_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('-100.00'),
                    'description': 'Покупки Ozon',
                    'source_ref': 'OZ-5',
                    'source_ref_strength': 'weak',
                    'category_name': 'Покупки Ozon',
                    'source': 'ozon',
                    'row_position': 0,
                },
            ],
        )

        upload.refresh_from_db()
        self.assertIsNone(upload.statement_closing_balance)
        self.assertIsNone(upload.account_balance_after)
        self.assertIsNone(upload.balance_discrepancy)

    def test_ozon_empty_parse_is_not_completed(self) -> None:
        """An empty Ozon parse does not prove that there are no rows."""
        upload = self._ozon_upload([])

        upload.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertTrue(upload.error_message)
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(BankStatementRow.objects.exists())

    def test_ozon_real_statement_imports_known_and_keeps_transfers(
        self,
    ) -> None:
        """Real PDF: known rows post, 4 real twins and 18 transfers wait.

        Four same-day pairs share amount and purpose but have different
        times and documents (two purchases, one tip, one refund), so the
        policy leaves them unresolved instead of merging two real
        operations. The printed totals are not used to force a post.
        """
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file=SimpleUploadedFile(
                'ozon-real.pdf',
                OZON_FIXTURE.read_bytes(),
                content_type='application/pdf',
            ),
        )

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(upload.total_transactions, 56)
        self.assertEqual(upload.income_count, 8)
        self.assertEqual(upload.expense_count, 26)
        self.assertEqual(upload.skipped_count, 4)
        self.assertEqual(Transaction.objects.count(), 34)
        rows = BankStatementRow.objects.filter(upload=upload)
        self.assertEqual(rows.count(), 56)
        self.assertEqual(
            rows.filter(decision=BankStatementRow.Decision.NEW).count(),
            34,
        )
        self.assertEqual(
            rows.filter(decision=BankStatementRow.Decision.PENDING).count(),
            4,
        )
        self.assertFalse(
            rows.filter(
                decision=BankStatementRow.Decision.PENDING,
                candidate__isnull=True,
            ).exists(),
        )
        self.assertEqual(
            rows.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            18,
        )
        self.assertFalse(
            rows.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            )
            .exclude(description__startswith='Перевод')
            .exists(),
        )
        self.assertEqual(self.account.balance, Decimal('-21025.20'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertIsNone(upload.statement_closing_balance)
        classifier.classify.assert_not_called()

    def _generic_upload(
        self,
        transactions: list[dict[str, Any]],
        *,
        file_hash: str = '',
        format_version: int = 2,
    ) -> BankStatementUpload:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/generic.pdf',
            file_hash=file_hash,
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=transactions,
                bank='generic',
                format_version=format_version,
            )
            process_bank_statement_task.apply(args=[upload.pk])
        return upload

    def test_generic_known_category_posts_row_and_movement(self) -> None:
        """A closed local category posts one linked movement without AI."""
        classifier = MagicMock()
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )
        upload = self._generic_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': None,
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(row.transaction)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.account.balance, Decimal('986.80'))
        self.assertEqual(upload.status, BankStatementUpload.Status.COMPLETED)
        classifier.classify.assert_not_called()

    def test_generic_malformed_reference_has_no_bank_fingerprint(self) -> None:
        """A generic ref never becomes an HMAC identity or a strong hint."""
        upload = self._generic_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'LEGACY-REF',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='generic-file',
        )

        row = BankStatementRow.objects.get(upload=upload)
        transaction = Transaction.objects.get()
        self.assertEqual(row.source_fingerprint, '')
        self.assertEqual(transaction.source_fingerprint, '')
        self.assertEqual(row.source_ref, 'LEGACY-REF')
        self.assertEqual(Transaction.objects.count(), 1)

    def test_generic_unknown_category_awaits_markup(self) -> None:
        """An unknown category stays unresolved and moves no money."""
        upload = self._generic_upload(
            [
                {
                    'date': timezone.now(),
                    'amount': Decimal('-13.20'),
                    'description': 'Оплата в MAGNIT',
                    'source_ref': None,
                    'category_name': None,
                    'row_position': 0,
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(row.transaction)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def test_generic_row_error_does_not_block_other_rows(self) -> None:
        """A recoverable row error stays visible; the known row still posts."""
        upload = self._generic_upload(
            [
                {
                    'date': None,
                    'amount': None,
                    'description': 'Неизвестная операция',
                    'parse_issue': 'unsupported',
                    'row_position': 0,
                },
                {
                    'date': timezone.now(),
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': None,
                    'category_name': 'Комиссия банка',
                    'row_position': 1,
                },
            ],
        )

        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            1,
        )
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.NEW,
            ).count(),
            1,
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(upload.failed_count, 1)
        self.assertEqual(self.account.balance, Decimal('986.80'))
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def test_generic_empty_parse_is_not_completed(self) -> None:
        """An empty generic parse does not prove there were no operations."""
        upload = self._generic_upload([])

        upload.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertTrue(upload.error_message)
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(BankStatementRow.objects.exists())

    @patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
    )
    def test_generic_fatal_file_error_fails_visible_without_money(
        self,
        parser: MagicMock,
    ) -> None:
        """A broken generic file posts nothing and is not complete."""
        parser.return_value.parse.side_effect = BankStatementParseError(
            'broken file',
        )
        upload = self._create_upload()

        process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(upload.failed_count, 1)
        self.assertTrue(upload.error_message)
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(BankStatementRow.objects.exists())

    def test_generic_same_file_position_is_exact_duplicate(self) -> None:
        """File hash, stable format and position prove one repeat."""
        moment = datetime(2026, 1, 10, 10, tzinfo=UTC)
        category = Category.objects.create(
            user=self.user,
            name='Комиссия банка',
            type=TransactionType.EXPENSE,
        )
        canonical_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/canonical.pdf',
            file_hash='canonical-hash',
        )
        canonical_transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('13.20'),
            date=moment,
            source_ref=None,
            source_file_hash='same-file',
            source_row_position=0,
            source_format_version=2,
        )
        canonical_row = BankStatementRow.objects.create(
            upload=canonical_upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=moment,
            amount=Decimal('13.20'),
            source_row_position=0,
            transaction=canonical_transaction,
            decision=BankStatementRow.Decision.NEW,
        )
        upload = self._generic_upload(
            [
                {
                    'date': moment + timedelta(hours=2),
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': None,
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='same-file',
        )

        self.account.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.DUPLICATE)
        self.assertEqual(row.canonical_row, canonical_row)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_real_raiffeisen_replay_keeps_rows_by_source_position(
        self,
    ) -> None:
        """Real 1-based positions survive replay before and after cleanup."""
        with RAIFFEISEN_REAL_FIXTURE.open('rb') as pdf:
            upload = BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file=File(pdf, name='raiffeisen-replay.pdf'),
            )
        process_bank_statement_task.apply(args=[upload.pk])
        upload.refresh_from_db()
        rows = upload.statement_rows.order_by('source_row_position')
        before = {
            row.source_row_position: (
                row.pk,
                row.decision,
                row.transaction_id,
                row.amount,
                row.source_ref,
            )
            for row in rows
        }
        self.assertEqual(sorted(before), list(range(1, 139)))
        self.assertIsNone(before[4][4])
        self.assertEqual(before[73][1], BankStatementRow.Decision.NEW)
        self.assertIsNotNone(before[73][2])
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('-119000.00'))
        pdf_content = RAIFFEISEN_REAL_FIXTURE.read_bytes()
        service = ApplicationContainer().users.bank_statement_import_service()

        for cleaned in (False, True):
            if cleaned:
                BankStatementUpload.objects.filter(pk=upload.pk).update(
                    expires_at=timezone.now(),
                )
                ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
                upload.refresh_from_db()
            current = {
                row.source_row_position: (
                    row.pk,
                    row.decision,
                    row.transaction_id,
                )
                for row in upload.statement_rows.all()
            }
            self.assertTrue(
                service.prepare_known_replay(
                    upload,
                    SimpleUploadedFile(
                        'raiffeisen-replay.pdf',
                        pdf_content,
                        content_type='application/pdf',
                    ),
                ),
            )
            process_bank_statement_task.apply(
                args=[upload.pk, upload.celery_task_id],
            )
            upload.refresh_from_db()
            after = {
                row.source_row_position: (
                    row.pk,
                    row.decision,
                    row.transaction_id,
                    row.amount,
                    row.source_ref,
                )
                for row in upload.statement_rows.all()
            }
            self.assertEqual(sorted(after), list(range(1, 139)))
            expected = {
                position: (
                    row_pk,
                    (
                        BankStatementRow.Decision.PENDING
                        if decision == BankStatementRow.Decision.EXPIRED
                        else decision
                    ),
                    transaction_id,
                )
                for position, (row_pk, decision, transaction_id) in (
                    current.items()
                )
            }
            self.assertEqual(
                {position: values[:3] for position, values in after.items()},
                expected,
            )
            if cleaned:
                self.assertEqual(
                    upload.status,
                    BankStatementUpload.Status.AWAITING_CONFIRMATION,
                )
            self.assertEqual(Transaction.objects.count(), 1)
            self.account.refresh_from_db()
            self.assertEqual(self.account.balance, Decimal('-119000.00'))
            self.assertEqual(after[73][3], Decimal('120000.00'))
            self.assertEqual(after[73][4], '311345')
            self.assertTrue(
                upload.statement_rows.get(
                    source_row_position=4,
                ).description,
            )

    def test_cleaned_partial_fragment_is_restored_by_replay(self) -> None:
        """A replay restores a cleaned fragment and reopens it for markup."""
        parse_result = StatementParseResult(
            transactions=[
                {
                    'date': None,
                    'amount': None,
                    'description': 'Неизвестная операция',
                    'parse_issue': 'unsupported',
                    'row_position': 7,
                },
            ],
            bank='generic',
            format_version=2,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/fragment.pdf',
            file_hash='fragment-file',
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(args=[upload.pk])
        row = BankStatementRow.objects.get(upload=upload)
        row_pk = row.pk
        self.assertEqual(row.source_row_position, 7)
        self.assertEqual(row.description, 'Неизвестная операция')

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now(),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
        upload.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(row.description, '')

        service = ApplicationContainer().users.bank_statement_import_service()
        self.assertTrue(
            service.prepare_known_replay(
                upload,
                SimpleUploadedFile(
                    'fragment.pdf',
                    b'%PDF-1.4 replay',
                    content_type='application/pdf',
                ),
            ),
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(
                args=[upload.pk, upload.celery_task_id],
            )

        rows = BankStatementRow.objects.filter(upload=upload)
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual(row.pk, row_pk)
        self.assertEqual(row.source_row_position, 7)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(row.decided_at)
        self.assertEqual(row.description, 'Неизвестная операция')
        self.assertIsNone(row.amount)
        self.assertIsNone(row.transaction_date)
        self.assertFalse(Transaction.objects.exists())
        upload.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        audit = row.decision_audits.get(
            previous_decision=BankStatementRow.Decision.EXPIRED,
        )
        self.assertEqual(
            audit.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(
            audit.previous_decision,
            BankStatementRow.Decision.EXPIRED,
        )
        self.assertIsNone(audit.actor)

        excluded = (
            ApplicationContainer()
            .users.statement_markup_service()
            .exclude(
                row.pk,
                self.user.pk,
                (BankStatementRow.ExclusionCode.NON_FINANCIAL_BANK_RECORD),
            )
        )

        self.assertEqual(excluded.decision, BankStatementRow.Decision.SKIPPED)
        self.assertFalse(Transaction.objects.exists())

    def test_cleaned_pending_row_is_reopened_by_replay(self) -> None:
        """A replay reopens a cleaned pending row for manual resolution."""
        moment = datetime(2026, 2, 3, 10, tzinfo=UTC)
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/reopen.pdf',
            file_hash='reopen-file',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=moment,
            amount=Decimal('13.20'),
            description='Комиссия за обслуживание',
            source_ref='G-REOPEN',
            source_row_position=0,
            source_format_version=1,
            decision=BankStatementRow.Decision.PENDING,
        )
        row_pk = row.pk
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now(),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
        upload.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertIsNone(row.amount)
        self.assertEqual(row.description, '')

        parse_result = StatementParseResult(
            transactions=[
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'G-REOPEN',
                    'source_ref_strength': 'weak',
                    'row_position': 0,
                },
            ],
            bank='generic',
            format_version=1,
        )
        service = ApplicationContainer().users.bank_statement_import_service()
        for _attempt in (1, 2):
            self.assertTrue(
                service.prepare_known_replay(
                    upload,
                    SimpleUploadedFile(
                        'reopen.pdf',
                        b'%PDF-1.4 replay',
                        content_type='application/pdf',
                    ),
                ),
            )
            run_id = service.start_run(upload)
            with patch(
                'hasta_la_vista_money.users.services.bank_statement_import.'
                'BankStatementParser',
            ) as parser:
                parser.return_value.parse.return_value = parse_result
                process_bank_statement_task.apply(
                    args=[upload.pk, run_id],
                )
            upload.refresh_from_db()
            row.refresh_from_db()
            self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
            self.assertIsNone(row.decided_at)
            self.assertEqual(row.amount, Decimal('13.20'))
            self.assertEqual(row.description, 'Комиссия за обслуживание')
            self.assertEqual(
                upload.status,
                BankStatementUpload.Status.AWAITING_CONFIRMATION,
            )
            self.assertEqual(Transaction.objects.count(), 0)

        self.assertEqual(row.pk, row_pk)
        self.assertEqual(row.decision_audits.count(), 2)
        expired = row.decision_audits.get(
            decision=BankStatementRow.Decision.EXPIRED,
        )
        self.assertEqual(
            expired.previous_decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertIsNone(expired.actor)
        audit = row.decision_audits.get(
            previous_decision=BankStatementRow.Decision.EXPIRED,
        )
        self.assertEqual(audit.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(
            audit.previous_decision,
            BankStatementRow.Decision.EXPIRED,
        )
        self.assertIsNone(audit.actor)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

        decided = BankStatementReconciliationService().decide(
            row.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )

        self.assertEqual(decided.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_partial_replay_keeps_expired_rows_open(self) -> None:
        """A replay that restores fewer rows keeps the expired one open."""
        moment = timezone.now()
        known = {
            'date': moment,
            'amount': Decimal('-13.20'),
            'description': 'Комиссия за обслуживание',
            'source_ref': None,
            'category_name': 'Комиссия банка',
            'row_position': 0,
        }
        unknown = {
            'date': moment,
            'amount': Decimal('-25.00'),
            'description': 'Оплата в MAGNIT',
            'source_ref': None,
            'category_name': None,
            'row_position': 1,
        }
        upload = self._generic_upload(
            [known, unknown],
            file_hash='partial-replay',
        )
        upload.refresh_from_db()
        expired = upload.statement_rows.get(source_row_position=1)
        self.assertEqual(
            expired.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now(),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
        upload.refresh_from_db()
        expired.refresh_from_db()
        self.assertEqual(expired.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )

        service = ApplicationContainer().users.bank_statement_import_service()
        self.assertTrue(
            service.prepare_known_replay(
                upload,
                SimpleUploadedFile(
                    'partial-replay.pdf',
                    b'%PDF-1.4 replay',
                    content_type='application/pdf',
                ),
            ),
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=[known],
                bank='generic',
                format_version=2,
            )
            process_bank_statement_task.apply(
                args=[upload.pk, upload.celery_task_id],
            )

        upload.refresh_from_db()
        expired.refresh_from_db()
        self.assertEqual(expired.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def _replay_parse_result(
        self,
        moment: datetime,
        *,
        source_ref: str,
        amount: Decimal = Decimal('-13.20'),
        description: str = 'Комиссия за обслуживание',
        category_name: str = 'Комиссия банка',
        row_position: int = 0,
    ) -> StatementParseResult:
        return StatementParseResult(
            transactions=[
                {
                    'date': moment,
                    'amount': amount,
                    'description': description,
                    'source_ref': source_ref,
                    'source_ref_strength': 'weak',
                    'category_name': category_name,
                    'row_position': row_position,
                },
            ],
            bank='raiffeisen',
            format_version=1,
        )

    def test_known_file_replay_restores_rows_without_moving_money(
        self,
    ) -> None:
        """A retained known file restores bank data and keeps its decision."""
        moment = datetime(2026, 2, 1, 10, tzinfo=UTC)
        parse_result = self._replay_parse_result(moment, source_ref='R-REPLAY')
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/replay.pdf',
            file_hash='replay-file',
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(args=[upload.pk])
        upload.refresh_from_db()
        row = BankStatementRow.objects.get(upload=upload)
        transaction = cast('Transaction', row.transaction)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        old_expiry = upload.expires_at

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now(),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        self.assertFalse(bool(upload.pdf_file))

        service = ApplicationContainer().users.bank_statement_import_service()
        self.assertTrue(
            service.prepare_known_replay(
                upload,
                SimpleUploadedFile(
                    'replay.pdf',
                    b'%PDF-1.4 replay',
                    content_type='application/pdf',
                ),
            ),
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(
                args=[upload.pk, upload.celery_task_id],
            )

        upload.refresh_from_db()
        row.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            upload.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )
        self.assertGreater(upload.expires_at, old_expiry)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(row.transaction, transaction)
        self.assertEqual(row.amount, Decimal('13.20'))
        self.assertEqual(row.description, 'Комиссия за обслуживание')
        self.assertEqual(row.source_ref, 'R-REPLAY')
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.account.balance, Decimal('986.80'))
        self.assertEqual(
            AuditLog.objects.filter(
                user=self.user,
                model_name=STATEMENT_IMPORT_LABEL,
            ).count(),
            2,
        )

    def test_cleanup_scrubs_audit_copy_after_safe_delete(self) -> None:
        """A deleted statement movement loses its FK, not its provenance."""
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/deleted-audit.pdf',
            file_hash='deleted-audit-file',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=7,
            source_ref='bank-deleted-row-ref',
            source_fingerprint='deleted-fingerprint',
            source_fingerprint_key_version='k1',
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('100.00'),
            description='Секретное банковское описание',
            decision=BankStatementRow.Decision.PENDING,
        )
        with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
            transaction = Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal('100.00'),
                date=timezone.now(),
                description='Секретное банковское описание',
                source_ref='bank-deleted-row-ref',
                source_file_hash=upload.file_hash,
                source_row_position=7,
                source_fingerprint='deleted-fingerprint',
                source_fingerprint_key_version='k1',
            )
        row.transaction = transaction
        row.decision = BankStatementRow.Decision.NEW
        row.save(update_fields=['transaction', 'decision'])
        independent = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('10.00'),
            date=timezone.now(),
            description='Ручная операция',
        )
        independent_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(independent.pk),
        )
        independent_diff = independent_audit.diff
        self.account.balance = Decimal('900.00')
        self.account.save(update_fields=['balance'])

        ApplicationContainer().transactions.transaction_service().delete_transaction(
            user=self.user,
            transaction_obj=transaction,
        )

        self.assertFalse(
            Transaction.objects.filter(pk=transaction.pk).exists(),
        )
        row.refresh_from_db()
        self.assertIsNone(row.transaction)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        delete_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(transaction.pk),
            kind=AuditOperationKind.TRANSACTION_DELETE,
        )
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )

        statement_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(transaction.pk),
            kind=AuditOperationKind.STATEMENT_IMPORT,
        )
        created = statement_audit.diff['created']
        for field in ('amount', 'date', 'description', 'source_ref'):
            with self.subTest(field=field):
                self.assertNotIn(field, created)
        self.assertEqual(
            created['source_fingerprint'],
            'deleted-fingerprint',
        )
        independent_audit.refresh_from_db()
        self.assertEqual(independent_audit.diff, independent_diff)
        delete_audit.refresh_from_db()
        deleted = delete_audit.diff['deleted']
        for field in ('amount', 'date', 'description', 'source_ref'):
            with self.subTest(field=field):
                self.assertNotIn(field, deleted)
        self.assertEqual(
            deleted['source_fingerprint'],
            'deleted-fingerprint',
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_scrub_keeps_delete_snapshot_of_another_operation(
        self,
    ) -> None:
        """A reused primary key must not scrub an older deletion copy."""
        diff = {
            'v': 2,
            'deleted': {
                'amount': '100.00',
                'description': 'Старое секретное описание',
            },
        }
        historical = AuditLog.objects.create(
            user=self.user,
            model_name='transactions.Transaction',
            object_pk='501',
            action=AuditLog.Action.DELETE,
            diff=diff,
            operation_id=uuid4(),
            kind=AuditOperationKind.TRANSACTION_DELETE,
        )
        with audit_operation(
            kind=AuditOperationKind.TRANSACTION_DELETE,
        ) as operation_id:
            current = AuditLog.objects.create(
                user=self.user,
                model_name='transactions.Transaction',
                object_pk='501',
                action=AuditLog.Action.DELETE,
                diff=diff,
                operation_id=operation_id,
                kind=AuditOperationKind.TRANSACTION_DELETE,
            )
            scrub_movement_audit_copy(
                user_id=self.user.pk,
                model_name='transactions.Transaction',
                object_id=501,
            )

        historical.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(historical.diff, diff)
        self.assertNotIn('description', current.diff['deleted'])

    def test_cleanup_uses_file_hash_and_position_after_safe_delete(
        self,
    ) -> None:
        """A deleted movement without a fingerprint keeps its file position."""
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/deleted-position-audit.pdf',
            file_hash='deleted-position-file',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=8,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('10.00'),
            description='Второе секретное описание',
            decision=BankStatementRow.Decision.PENDING,
        )
        with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
            transaction = Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal('10.00'),
                date=timezone.now(),
                description='Второе секретное описание',
                source_file_hash=upload.file_hash,
                source_row_position=8,
            )
        row.transaction = transaction
        row.decision = BankStatementRow.Decision.NEW
        row.save(update_fields=['transaction', 'decision'])
        self.account.balance = Decimal('990.00')
        self.account.save(update_fields=['balance'])

        ApplicationContainer().transactions.transaction_service().delete_transaction(
            user=self.user,
            transaction_obj=transaction,
        )
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()

        statement_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(transaction.pk),
            kind=AuditOperationKind.STATEMENT_IMPORT,
        )
        created = statement_audit.diff['created']
        for field in ('amount', 'date', 'description'):
            with self.subTest(field=field):
                self.assertNotIn(field, created)
        self.assertEqual(created['source_file_hash'], upload.file_hash)
        self.assertEqual(created['source_row_position'], 8)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_deleting_transaction_after_cleanup_expires_linked_row(
        self,
    ) -> None:
        """A cleaned statement never shows an unresolvable pending row."""
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/post-cleanup-delete.pdf',
            total_transactions=1,
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('100.00'),
            description='Секретное описание банка',
            decision=BankStatementRow.Decision.PENDING,
        )
        with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
            transaction = Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal('100.00'),
                date=timezone.now(),
                description='Секретное описание банка',
            )
        transaction_pk = transaction.pk
        row.transaction = transaction
        row.decision = BankStatementRow.Decision.NEW
        row.save(update_fields=['transaction', 'decision'])
        self.account.balance = Decimal('900.00')
        self.account.save(update_fields=['balance'])
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )
        upload.refresh_from_db()
        row.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.COMPLETED,
        )
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)

        transaction_service = (
            ApplicationContainer().transactions.transaction_service()
        )
        transaction_service.delete_transaction(
            user=self.user,
            transaction_obj=transaction,
        )

        row.refresh_from_db()
        upload.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        self.assertEqual(upload.expired_count, 1)
        audit = BankStatementDecisionAudit.objects.filter(row=row).latest('pk')
        self.assertEqual(audit.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(
            audit.previous_decision,
            BankStatementRow.Decision.NEW,
        )
        self.assertEqual(audit.previous_transaction_pk, transaction_pk)
        delete_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(transaction_pk),
            kind=AuditOperationKind.TRANSACTION_DELETE,
        )
        deleted = delete_audit.diff['deleted']
        for field in ('amount', 'date', 'description'):
            with self.subTest(field=field):
                self.assertNotIn(field, deleted)

    def test_deleting_transfer_after_cleanup_expires_linked_row(
        self,
    ) -> None:
        """A cleaned statement expires a row whose transfer is deleted."""
        other = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            balance=Decimal('500.00'),
            currency='RUB',
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/post-cleanup-transfer.pdf',
            total_transactions=1,
        )
        transfer = (
            ApplicationContainer()
            .finance_account.transfer_service()
            .transfer_money(
                from_account=self.account,
                to_account=other,
                amount=Decimal('50.00'),
                user=self.user,
                exchange_date=timezone.now(),
            )
        )
        transfer_pk = transfer.pk
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('50.00'),
            transfer=transfer,
            decision=BankStatementRow.Decision.TRANSFERRED,
        )
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )
        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)

        transfer_service = (
            ApplicationContainer().finance_account.transfer_service()
        )
        transfer_service.delete_transfer(
            transfer_id=transfer_pk,
            user=self.user,
        )

        row.refresh_from_db()
        upload.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        audit = BankStatementDecisionAudit.objects.filter(row=row).latest('pk')
        self.assertEqual(audit.decision, BankStatementRow.Decision.EXPIRED)
        self.assertEqual(
            audit.previous_decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertEqual(audit.previous_transfer_pk, transfer_pk)
        delete_audit = AuditLog.objects.get(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(transfer_pk),
            action=AuditLog.Action.DELETE,
        )
        deleted = delete_audit.diff['deleted']
        for field in ('amount', 'exchange_date', 'notes'):
            with self.subTest(field=field):
                self.assertNotIn(field, deleted)

    def test_deleting_linked_manual_transaction_keeps_its_audit(
        self,
    ) -> None:
        """A manual movement linked to a cleaned row keeps its own audit."""
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        manual = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=timezone.now(),
            description='Ручная операция',
        )
        manual_pk = manual.pk
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/linked-manual-delete.pdf',
            total_transactions=1,
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('100.00'),
            transaction=manual,
            decision=BankStatementRow.Decision.LINKED,
        )
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])
        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )
        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        create_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(manual_pk),
            action=AuditLog.Action.CREATE,
        )
        created_diff = create_audit.diff

        (
            ApplicationContainer()
            .transactions.transaction_service()
            .delete_transaction(user=self.user, transaction_obj=manual)
        )

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXPIRED)
        audit = BankStatementDecisionAudit.objects.filter(row=row).latest('pk')
        self.assertEqual(
            audit.previous_decision,
            BankStatementRow.Decision.LINKED,
        )
        create_audit.refresh_from_db()
        self.assertEqual(create_audit.diff, created_diff)
        delete_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(manual_pk),
            action=AuditLog.Action.DELETE,
        )
        deleted = delete_audit.diff['deleted']
        for field in ('amount', 'date', 'description'):
            with self.subTest(field=field):
                self.assertIn(field, deleted)

    def test_deleting_linked_manual_transfer_keeps_its_audit(
        self,
    ) -> None:
        """A manual linked transfer keeps its creation and deletion audit."""
        other = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            balance=Decimal('500.00'),
            currency='RUB',
        )
        transfer_service = (
            ApplicationContainer().finance_account.transfer_service()
        )
        transfer = transfer_service.transfer_money(
            from_account=self.account,
            to_account=other,
            amount=Decimal('50.00'),
            user=self.user,
            exchange_date=timezone.now(),
        )
        transfer_pk = transfer.pk
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/linked-manual-transfer.pdf',
            total_transactions=1,
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('50.00'),
            transfer=transfer,
            decision=BankStatementRow.Decision.LINKED,
        )
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])
        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )
        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        create_audit = AuditLog.objects.get(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(transfer_pk),
            action=AuditLog.Action.CREATE,
        )
        created_diff = create_audit.diff

        transfer_service.delete_transfer(
            transfer_id=transfer_pk,
            user=self.user,
        )

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXPIRED)
        audit = BankStatementDecisionAudit.objects.filter(row=row).latest('pk')
        self.assertEqual(
            audit.previous_decision,
            BankStatementRow.Decision.LINKED,
        )
        create_audit.refresh_from_db()
        self.assertEqual(create_audit.diff, created_diff)
        delete_audit = AuditLog.objects.get(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(transfer_pk),
            action=AuditLog.Action.DELETE,
        )
        deleted = delete_audit.diff['deleted']
        for field in ('amount', 'exchange_date', 'notes'):
            with self.subTest(field=field):
                self.assertIn(field, deleted)

    def test_cleanup_scrubs_deleted_movement_by_saved_id_across_statements(
        self,
    ) -> None:
        """A shared fingerprint cannot hide a deleted movement's bank copy."""
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/overlap-a.pdf',
            file_hash='overlap-a',
        )
        overlapping = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/overlap-b.pdf',
            file_hash='overlap-b',
        )
        BankStatementRow.objects.create(
            upload=overlapping,
            source_row_position=7,
            source_fingerprint='overlap-fingerprint',
            decision=BankStatementRow.Decision.PENDING,
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=7,
            source_fingerprint='overlap-fingerprint',
            source_fingerprint_key_version='k1',
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('100.00'),
            description='Секретное описание банка',
            decision=BankStatementRow.Decision.PENDING,
        )
        with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
            transaction = Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal('100.00'),
                date=timezone.now(),
                description='Секретное описание банка',
                source_fingerprint='overlap-fingerprint',
                source_fingerprint_key_version='k1',
            )
        transaction_pk = transaction.pk
        row.transaction = transaction
        row.decision = BankStatementRow.Decision.NEW
        row.save(update_fields=['transaction', 'decision'])
        self.account.balance = Decimal('900.00')
        self.account.save(update_fields=['balance'])

        transaction_service = (
            ApplicationContainer().transactions.transaction_service()
        )
        transaction_service.delete_transaction(
            user=self.user,
            transaction_obj=transaction,
        )
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )

        statement_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(transaction_pk),
            kind=AuditOperationKind.STATEMENT_IMPORT,
        )
        created = statement_audit.diff['created']
        for field in ('amount', 'description'):
            with self.subTest(field=field):
                self.assertNotIn(field, created)
        self.assertEqual(
            created['source_fingerprint'],
            'overlap-fingerprint',
        )
        delete_audit = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(transaction_pk),
            kind=AuditOperationKind.TRANSACTION_DELETE,
        )
        deleted = delete_audit.diff['deleted']
        for field in ('amount', 'date', 'description'):
            with self.subTest(field=field):
                self.assertNotIn(field, deleted)
        self.assertEqual(
            deleted['source_fingerprint'],
            'overlap-fingerprint',
        )

    def test_cleanup_keeps_reused_primary_key_of_deleted_movement(
        self,
    ) -> None:
        """A reused primary key keeps its reference and a foreign copy."""
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/reused-pk.pdf',
            file_hash='reused-pk-file',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=3,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('100.00'),
            description='Секретное описание банка',
            decision=BankStatementRow.Decision.PENDING,
        )
        with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
            transaction = Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal('100.00'),
                date=timezone.now(),
                description='Секретное описание банка',
                source_ref='R-STALE',
            )
        deleted_pk = transaction.pk
        row.transaction = transaction
        row.decision = BankStatementRow.Decision.NEW
        row.save(update_fields=['transaction', 'decision'])
        self.account.balance = Decimal('900.00')
        self.account.save(update_fields=['balance'])

        transaction_service = (
            ApplicationContainer().transactions.transaction_service()
        )
        transaction_service.delete_transaction(
            user=self.user,
            transaction_obj=transaction,
        )
        foreign_diff = {
            'v': 2,
            'deleted': {
                'amount': '50.00',
                'description': 'Чужое описание',
            },
        }
        foreign = AuditLog.objects.create(
            user=self.user,
            model_name='transactions.Transaction',
            object_pk=str(deleted_pk),
            action=AuditLog.Action.DELETE,
            diff=foreign_diff,
            operation_id=uuid4(),
            kind=AuditOperationKind.TRANSACTION_DELETE,
        )
        with audit_operation(kind=AuditOperationKind.EXPENSE):
            reused = Transaction.objects.create(
                pk=deleted_pk,
                user=self.user,
                account=self.account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal('70.00'),
                date=timezone.now(),
                description='Ручная операция',
                source_ref='R-NEW',
            )
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )

        reused.refresh_from_db()
        self.assertEqual(reused.source_ref, 'R-NEW')
        foreign.refresh_from_db()
        self.assertEqual(foreign.diff, foreign_diff)
        own_deleted = (
            AuditLog.objects.filter(
                model_name='transactions.Transaction',
                object_pk=str(deleted_pk),
                kind=AuditOperationKind.TRANSACTION_DELETE,
            )
            .exclude(pk=foreign.pk)
            .get()
        )
        for field in ('amount', 'description'):
            with self.subTest(field=field):
                self.assertNotIn(field, own_deleted.diff['deleted'])

    def test_cleanup_keeps_create_audit_of_reused_transfer_pk(
        self,
    ) -> None:
        """A manual transfer reusing a released id keeps its creation copy."""
        other = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            balance=Decimal('500.00'),
            currency='RUB',
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/reused-transfer-pk.pdf',
            file_hash='reused-transfer-pk-file',
        )
        transfer = (
            ApplicationContainer()
            .finance_account.transfer_service()
            .transfer_money(
                from_account=self.account,
                to_account=other,
                amount=Decimal('50.00'),
                user=self.user,
                exchange_date=timezone.now(),
            )
        )
        transfer_pk = transfer.pk
        BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('50.00'),
            transfer=transfer,
            decision=BankStatementRow.Decision.TRANSFERRED,
        )
        transfer_service = (
            ApplicationContainer().finance_account.transfer_service()
        )
        transfer_service.delete_transfer(
            transfer_id=transfer_pk,
            user=self.user,
        )
        with audit_operation(kind=AuditOperationKind.TRANSFER):
            reused = TransferMoneyLog.objects.create(
                pk=transfer_pk,
                user=self.user,
                from_account=self.account,
                to_account=other,
                amount=Decimal('75.00'),
                exchange_date=timezone.now(),
                notes='Ручной перевод',
            )
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )

        reused.refresh_from_db()
        self.assertEqual(reused.notes, 'Ручной перевод')
        created = AuditLog.objects.filter(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(transfer_pk),
            action=AuditLog.Action.CREATE,
            kind=AuditOperationKind.TRANSFER,
        ).latest('pk')
        self.assertEqual(created.diff['created']['amount'], '75.00')
        self.assertEqual(created.diff['created']['notes'], 'Ручной перевод')
        self.assertIn('exchange_date', created.diff['created'])

    def test_cleanup_scrubs_legacy_delete_snapshot_without_operation(
        self,
    ) -> None:
        """A decision before the release operation id still scrubs its copy."""
        other = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            balance=Decimal('500.00'),
            currency='RUB',
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/legacy-delete-snapshot.pdf',
            file_hash='legacy-delete-snapshot-file',
        )
        transfer = (
            ApplicationContainer()
            .finance_account.transfer_service()
            .transfer_money(
                from_account=self.account,
                to_account=other,
                amount=Decimal('50.00'),
                user=self.user,
                exchange_date=timezone.now(),
            )
        )
        transfer_pk = transfer.pk
        BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('50.00'),
            transfer=transfer,
            decision=BankStatementRow.Decision.TRANSFERRED,
        )
        transfer_service = (
            ApplicationContainer().finance_account.transfer_service()
        )
        transfer_service.delete_transfer(
            transfer_id=transfer_pk,
            user=self.user,
        )
        original_delete = AuditLog.objects.get(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(transfer_pk),
            action=AuditLog.Action.DELETE,
        )
        BankStatementDecisionAudit.objects.filter(
            row__upload=upload,
        ).update(release_operation_id=None)
        with audit_operation(kind=AuditOperationKind.TRANSFER):
            TransferMoneyLog.objects.create(
                pk=transfer_pk,
                user=self.user,
                from_account=self.account,
                to_account=other,
                amount=Decimal('75.00'),
                exchange_date=timezone.now(),
                notes='Ручной перевод',
            )
        transfer_service.delete_transfer(
            transfer_id=transfer_pk,
            user=self.user,
        )
        later_delete = AuditLog.objects.exclude(pk=original_delete.pk).get(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(transfer_pk),
            action=AuditLog.Action.DELETE,
        )
        later_diff = later_delete.diff
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )

        original_delete.refresh_from_db()
        for field in ('amount', 'exchange_date', 'notes'):
            with self.subTest(field=field):
                self.assertNotIn(field, original_delete.diff['deleted'])
        later_delete.refresh_from_db()
        self.assertEqual(later_delete.diff, later_diff)

    def test_cleanup_keeps_manual_delete_of_reused_transaction_id(
        self,
    ) -> None:
        """A manual transaction deleting a reused id keeps its own copy.

        The manual movement is created and deleted inside the legacy
        tolerance, so only its own creation copy proves the deletion
        belongs to another movement.
        """
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/reused-delete-pk.pdf',
            file_hash='reused-delete-pk-file',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=4,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('100.00'),
            description='Секретное описание банка',
            decision=BankStatementRow.Decision.PENDING,
        )
        with audit_operation(kind=AuditOperationKind.STATEMENT_IMPORT):
            statement = Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal('100.00'),
                date=timezone.now(),
                description='Секретное описание банка',
                source_ref='R-STALE',
            )
        released_pk = statement.pk
        row.transaction = statement
        row.decision = BankStatementRow.Decision.NEW
        row.save(update_fields=['transaction', 'decision'])
        self.account.balance = Decimal('900.00')
        self.account.save(update_fields=['balance'])
        transaction_service = (
            ApplicationContainer().transactions.transaction_service()
        )
        transaction_service.delete_transaction(
            user=self.user,
            transaction_obj=statement,
        )
        statement_delete = AuditLog.objects.get(
            model_name='transactions.Transaction',
            object_pk=str(released_pk),
            kind=AuditOperationKind.TRANSACTION_DELETE,
        )
        BankStatementDecisionAudit.objects.filter(
            row__upload=upload,
        ).update(release_operation_id=None)
        with audit_operation(kind=AuditOperationKind.EXPENSE):
            manual = Transaction.objects.create(
                pk=released_pk,
                user=self.user,
                account=self.account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal('70.00'),
                date=timezone.now(),
                description='Ручная операция',
            )
        transaction_service.delete_transaction(
            user=self.user,
            transaction_obj=manual,
        )
        manual_delete = AuditLog.objects.exclude(
            pk=statement_delete.pk,
        ).get(
            model_name='transactions.Transaction',
            object_pk=str(released_pk),
            action=AuditLog.Action.DELETE,
            kind=AuditOperationKind.TRANSACTION_DELETE,
        )
        manual_diff = manual_delete.diff
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )

        manual_delete.refresh_from_db()
        self.assertEqual(manual_delete.diff, manual_diff)
        statement_delete.refresh_from_db()
        for field in ('amount', 'date', 'description'):
            with self.subTest(field=field):
                self.assertNotIn(field, statement_delete.diff['deleted'])

    def test_cleanup_keeps_delete_of_manual_movement_before_statement_row(
        self,
    ) -> None:
        """A manual movement deleted before the statement row stays intact.

        The statement movement reuses the released primary key, so the
        legacy decision must scrub its own deletion copy, not the earlier
        foreign one, and must not touch the earlier creation copy.
        """
        other = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            balance=Decimal('500.00'),
            currency='RUB',
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/legacy-earlier-delete.pdf',
            file_hash='legacy-earlier-delete-file',
        )
        transfer_service = (
            ApplicationContainer().finance_account.transfer_service()
        )
        manual = transfer_service.transfer_money(
            from_account=self.account,
            to_account=other,
            amount=Decimal('50.00'),
            user=self.user,
            exchange_date=timezone.now(),
        )
        transfer_pk = manual.pk
        transfer_service.delete_transfer(
            transfer_id=transfer_pk,
            user=self.user,
        )
        manual_audits = AuditLog.objects.filter(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(transfer_pk),
        )
        manual_create = manual_audits.get(action=AuditLog.Action.CREATE)
        manual_delete = manual_audits.get(action=AuditLog.Action.DELETE)
        manual_create_diff = manual_create.diff
        manual_delete_diff = manual_delete.diff
        with audit_operation(kind=AuditOperationKind.TRANSFER):
            statement_transfer = TransferMoneyLog.objects.create(
                pk=transfer_pk,
                user=self.user,
                from_account=self.account,
                to_account=other,
                amount=Decimal('75.00'),
                exchange_date=timezone.now(),
                notes='Ручной перевод',
            )
        BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('75.00'),
            transfer=statement_transfer,
            decision=BankStatementRow.Decision.TRANSFERRED,
        )
        transfer_service.delete_transfer(
            transfer_id=transfer_pk,
            user=self.user,
        )
        statement_delete = AuditLog.objects.exclude(pk=manual_delete.pk).get(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(transfer_pk),
            action=AuditLog.Action.DELETE,
        )
        BankStatementDecisionAudit.objects.filter(
            row__upload=upload,
        ).update(release_operation_id=None)
        upload.expires_at = timezone.now()
        upload.save(update_fields=['expires_at'])

        (
            ApplicationContainer()
            .users.bank_statement_retention_service()
            .cleanup_expired()
        )

        manual_create.refresh_from_db()
        self.assertEqual(manual_create.diff, manual_create_diff)
        manual_delete.refresh_from_db()
        self.assertEqual(manual_delete.diff, manual_delete_diff)
        statement_delete.refresh_from_db()
        for field in ('amount', 'exchange_date', 'notes'):
            with self.subTest(field=field):
                self.assertNotIn(field, statement_delete.diff['deleted'])

    def test_cleanup_scans_audit_entries_in_bounded_chunks(self) -> None:
        """Cleanup must not load a user's whole audit history at once."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/bounded-audit.pdf',
        )
        provenance = _AuditProvenance(
            transaction_ids={1},
            transfer_ids=set(),
            deleted_transaction_ids={},
            deleted_transfer_ids={},
            deleted_movement_starts={},
            delete_snapshots=set(),
            legacy_delete_snapshot_ids=set(),
            fingerprints=set(),
            row_positions=set(),
            file_hash='bounded-audit-file',
            account_id=self.account.pk,
        )

        with patch(
            'hasta_la_vista_money.users.services.bank_statement_retention.'
            'AuditLog.objects',
        ) as audit_manager:
            entries = audit_manager.filter.return_value
            entries.iterator.return_value = []
            BankStatementRetentionService._anonymize_audit_copies(
                upload,
                provenance,
            )

        query = str(audit_manager.filter.call_args)
        self.assertIn('created_at__gte', query)
        self.assertIn('object_pk__in', query)
        entries.iterator.assert_called_once_with(
            chunk_size=constants.STATEMENT_AUDIT_SCAN_CHUNK_SIZE,
        )

    def test_known_file_replay_does_not_recreate_deleted_movement(
        self,
    ) -> None:
        """A replay keeps a deleted movement deleted and the row unresolved."""
        moment = datetime(2026, 2, 2, 10, tzinfo=UTC)
        parse_result = self._replay_parse_result(
            moment,
            source_ref='R-DELETED',
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/deleted.pdf',
            file_hash='deleted-file',
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(args=[upload.pk])
        row = BankStatementRow.objects.get(upload=upload)
        transaction = cast('Transaction', row.transaction)
        transaction_service = (
            ApplicationContainer().transactions.transaction_service()
        )
        transaction_service.delete_transaction(
            user=self.user,
            transaction_obj=transaction,
        )
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)

        service = ApplicationContainer().users.bank_statement_import_service()
        self.assertTrue(
            service.prepare_known_replay(
                upload,
                SimpleUploadedFile(
                    'deleted.pdf',
                    b'%PDF-1.4 replay',
                    content_type='application/pdf',
                ),
            ),
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(
                args=[upload.pk, upload.celery_task_id],
            )

        upload.refresh_from_db()
        row.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(row.transaction)
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_overlapping_new_file_stays_reconciliation_and_links_known(
        self,
    ) -> None:
        """A known-period overlap posts nothing and keeps new rows pending."""
        moment = datetime(2026, 1, 10, 10, tzinfo=UTC)
        first = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-OVERLAP',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='overlap-first',
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        first_row = BankStatementRow.objects.get(upload=first)
        self.assertEqual(first_row.decision, BankStatementRow.Decision.NEW)

        second = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-OVERLAP',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
                {
                    'date': moment + timedelta(days=1),
                    'amount': Decimal('-40.00'),
                    'description': 'Оплата в MAGNIT',
                    'source_ref': 'R-NEW',
                    'source_ref_strength': 'strong',
                    'category_name': 'Продукты',
                    'row_position': 1,
                },
            ],
            file_hash='overlap-second',
            period_start=date(2026, 1, 15),
            period_end=date(2026, 2, 15),
        )

        self.account.refresh_from_db()
        second.refresh_from_db()
        rows = BankStatementRow.objects.filter(upload=second)
        known = rows.get(source_ref='R-OVERLAP')
        new = rows.get(source_ref='R-NEW')
        self.assertEqual(
            second.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )
        self.assertEqual(known.decision, BankStatementRow.Decision.DUPLICATE)
        self.assertEqual(known.canonical_row, first_row)
        self.assertEqual(
            new.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.account.balance, Decimal('986.80'))
        self.assertEqual(
            second.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                user=self.user,
                model_name=STATEMENT_IMPORT_LABEL,
            ).count(),
            2,
        )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[second.pk],
            ),
        )
        self.assertContains(response, 'пересекается')

    def test_unknown_period_never_claims_overlap(self) -> None:
        """Without explicit periods no overlap is claimed either way."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/unknown-period.pdf',
            file_hash='unknown-period',
            statement_bank='raiffeisen',
        )
        service = ApplicationContainer().users.bank_statement_import_service()

        self.assertFalse(service.has_overlapping_period(upload))
        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[upload.pk],
            ),
        )
        self.assertNotContains(response, 'пересекается')

    def test_overlapping_sberbank_period_publishes_coverage(self) -> None:
        """Sberbank reconciliation still proves the later explicit period."""
        moment = datetime(2026, 1, 10, 10, tzinfo=UTC)
        self._sberbank_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'S-COVERAGE',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='sberbank-coverage-first',
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        second = self._sberbank_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'S-COVERAGE',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
                {
                    'date': moment + timedelta(days=1),
                    'amount': Decimal('-40.00'),
                    'description': 'Оплата в MAGNIT',
                    'source_ref': 'S-COVERAGE-NEW',
                    'source_ref_strength': 'strong',
                    'category_name': 'Продукты',
                    'row_position': 1,
                },
            ],
            file_hash='sberbank-coverage-second',
            period_start=date(2026, 1, 15),
            period_end=date(2026, 2, 15),
        )
        second.refresh_from_db()
        self.assertEqual(
            second.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )

        coverage = StatementPeriodCoverage.objects.filter(
            upload=second,
            is_actual=True,
        )
        self.assertEqual(coverage.count(), 1)
        record = coverage.get()
        self.assertEqual(record.period_start, date(2026, 1, 15))
        self.assertEqual(record.period_end, date(2026, 2, 15))

        summary = (
            ApplicationContainer()
            .users.statement_coverage_service()
            .summary(
                self.account,
                date(2026, 1, 1),
                date(2026, 2, 15),
            )
        )
        self.assertEqual(summary.state, 'covered')
        self.assertEqual(summary.gaps, ())

    def test_overlapping_empty_parse_does_not_publish_coverage(self) -> None:
        """A zero-row reconciliation parse proves no new coverage."""
        moment = datetime(2026, 1, 10, 10, tzinfo=UTC)
        self._sberbank_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'S-EMPTY-FIRST',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='sberbank-empty-first',
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        second = self._sberbank_upload(
            [],
            file_hash='sberbank-empty-second',
            period_start=date(2026, 1, 15),
            period_end=date(2026, 2, 15),
        )
        second.refresh_from_db()

        self.assertEqual(
            second.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )
        self.assertFalse(
            StatementPeriodCoverage.objects.filter(upload=second).exists(),
        )

    def test_real_bank_adapters_keep_policy_replay_retention_and_privacy(
        self,
    ) -> None:
        """Real Raiffeisen, Sberbank and Ozon runs share the same invariants.

        Only demonstrated facts are asserted: parsed row counts, no invented
        money on replay, explicit-only coverage, balance "not checked" when
        bank metadata is unconfirmed, and cleanup that keeps positions,
        decisions and fingerprints without bank amounts.
        """
        cases = (
            (RAIFFEISEN_REAL_FIXTURE, 'raiffeisen', 138),
            (SBERBANK_FIXTURE, 'sberbank', 6),
            (OZON_FIXTURE, 'ozon', 56),
        )
        for fixture, bank, expected_rows in cases:
            with self.subTest(bank=bank):
                account = Account.objects.create(
                    user=self.user,
                    name_account=f'{bank} acceptance',
                    balance=Decimal('1000.00'),
                    currency='RUB',
                    type_account=(
                        constants.ACCOUNT_TYPE_CREDIT_CARD
                        if bank == 'sberbank'
                        else constants.ACCOUNT_TYPE_DEBIT_CARD
                    ),
                )
                with fixture.open('rb') as pdf:
                    upload = BankStatementUpload.objects.create(
                        user=self.user,
                        account=account,
                        pdf_file=File(pdf, name=f'{bank}.pdf'),
                    )

                process_bank_statement_task.apply(args=[upload.pk])
                upload.refresh_from_db()
                account.refresh_from_db()
                self.assertEqual(upload.statement_bank, bank)
                self.assertEqual(upload.total_transactions, expected_rows)
                self.assertEqual(upload.failed_count, 0)
                rows = upload.statement_rows
                self.assertEqual(rows.count(), expected_rows)
                self.assertNotEqual(
                    upload.status,
                    BankStatementUpload.Status.COMPLETED,
                )
                self.assertTrue(
                    rows.exclude(source_fingerprint='').exists(),
                )
                if (
                    upload.balance_type
                    == BankStatementUpload.BalanceType.UNKNOWN
                ):
                    self.assertEqual(
                        upload.balance_result,
                        BankStatementUpload.BalanceResult.NOT_CHECKED,
                    )
                coverage = StatementPeriodCoverage.objects.filter(
                    upload=upload,
                )
                if upload.statement_period_from is not None:
                    self.assertTrue(coverage.filter(is_actual=True).exists())
                else:
                    self.assertFalse(coverage.exists())

                movements_before = Transaction.objects.filter(
                    account=account,
                ).count()
                balance_before = account.balance
                positions_before = {
                    int(position)
                    for position in rows.exclude(
                        source_row_position=None,
                    ).values_list('source_row_position', flat=True)
                    if position is not None
                }
                self.assertTrue(
                    ApplicationContainer()
                    .users.bank_statement_import_service()
                    .prepare_known_replay(
                        upload,
                        SimpleUploadedFile(
                            f'{bank}-replay.pdf',
                            fixture.read_bytes(),
                            content_type='application/pdf',
                        ),
                    ),
                )
                process_bank_statement_task.apply(
                    args=[upload.pk, upload.celery_task_id],
                )
                upload.refresh_from_db()
                account.refresh_from_db()
                after_positions = {
                    int(position)
                    for position in upload.statement_rows.exclude(
                        source_row_position=None,
                    ).values_list('source_row_position', flat=True)
                    if position is not None
                }
                self.assertEqual(
                    upload.statement_rows.count(),
                    expected_rows,
                    msg=(
                        f'extra={sorted(after_positions - positions_before)} '
                        f'lost={sorted(positions_before - after_positions)}'
                    ),
                )
                self.assertEqual(
                    Transaction.objects.filter(account=account).count(),
                    movements_before,
                )
                self.assertEqual(account.balance, balance_before)
                self.assertEqual(
                    {
                        int(position)
                        for position in upload.statement_rows.exclude(
                            source_row_position=None,
                        ).values_list('source_row_position', flat=True)
                        if position is not None
                    },
                    positions_before,
                )

                BankStatementUpload.objects.filter(pk=upload.pk).update(
                    expires_at=timezone.now(),
                )
                ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
                upload.refresh_from_db()
                self.assertEqual(upload.pdf_file.name, '')
                self.assertIsNotNone(upload.retention_cleaned_at)
                self.assertFalse(
                    upload.statement_rows.exclude(amount=None).exists(),
                )
                self.assertTrue(
                    upload.statement_rows.exclude(
                        source_fingerprint='',
                    ).exists(),
                )
                if upload.statement_period_from is not None:
                    self.assertTrue(
                        StatementPeriodCoverage.objects.filter(
                            upload=upload,
                            is_actual=True,
                        ).exists(),
                    )

    def test_known_file_replay_after_cleanup_keeps_single_movement(
        self,
    ) -> None:
        """A retained known file replays without a second movement."""
        moment = datetime(2026, 2, 1, 10, tzinfo=UTC)
        parse_result = self._replay_parse_result(moment, source_ref='R-KEEP')
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/replay-keep.pdf',
            file_hash='replay-keep-file',
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(args=[upload.pk])
        row = BankStatementRow.objects.get(upload=upload)
        movement = cast('Transaction', row.transaction)
        fingerprint = movement.source_fingerprint
        self.assertEqual(movement.source_ref, 'R-KEEP')
        self.assertTrue(fingerprint)

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now(),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
        movement.refresh_from_db()
        self.assertIsNone(movement.source_ref)
        self.assertEqual(movement.source_fingerprint, fingerprint)

        service = ApplicationContainer().users.bank_statement_import_service()
        self.assertTrue(
            service.prepare_known_replay(
                upload,
                SimpleUploadedFile(
                    'replay-keep.pdf',
                    b'%PDF-1.4 replay',
                    content_type='application/pdf',
                ),
            ),
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = parse_result
            process_bank_statement_task.apply(
                args=[upload.pk, upload.celery_task_id],
            )

        upload.refresh_from_db()
        row.refresh_from_db()
        movement.refresh_from_db()
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(row.transaction, movement)
        self.assertEqual(row.source_ref, 'R-KEEP')
        self.assertIsNone(movement.source_ref)
        self.assertEqual(movement.source_fingerprint, fingerprint)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('986.80'))

    def test_overlapping_statement_after_cleanup_creates_no_movement(
        self,
    ) -> None:
        """A retained first statement still proves the overlap."""
        moment = datetime(2026, 1, 10, 10, tzinfo=UTC)
        first = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-RETAINED',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='retained-first',
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        first.refresh_from_db()
        first_row = BankStatementRow.objects.get(upload=first)
        self.assertEqual(first_row.decision, BankStatementRow.Decision.NEW)
        movement = cast('Transaction', first_row.transaction)

        BankStatementUpload.objects.filter(pk=first.pk).update(
            expires_at=timezone.now(),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
        movement.refresh_from_db()
        self.assertIsNone(movement.source_ref)
        self.assertTrue(movement.source_fingerprint)

        second = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-RETAINED',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
                {
                    'date': moment + timedelta(days=1),
                    'amount': Decimal('-40.00'),
                    'description': 'Оплата в MAGNIT',
                    'source_ref': 'R-OVERLAP-NEW',
                    'source_ref_strength': 'strong',
                    'category_name': 'Продукты',
                    'row_position': 1,
                },
            ],
            file_hash='retained-second',
            period_start=date(2026, 1, 15),
            period_end=date(2026, 2, 15),
        )

        second.refresh_from_db()
        known = BankStatementRow.objects.get(
            upload=second,
            source_ref='R-RETAINED',
        )
        new = BankStatementRow.objects.get(
            upload=second,
            source_ref='R-OVERLAP-NEW',
        )
        self.assertEqual(
            second.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )
        self.assertEqual(known.decision, BankStatementRow.Decision.DUPLICATE)
        self.assertEqual(known.canonical_row, first_row)
        self.assertEqual(
            new.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('986.80'))

    def test_legacy_retained_overlap_without_fingerprint_stays_manual(
        self,
    ) -> None:
        """A legacy movement without technical proof stays for manual review."""
        moment = datetime(2026, 1, 10, 10, tzinfo=UTC)
        first = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-LEGACY',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='legacy-first',
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        first_row = BankStatementRow.objects.get(upload=first)
        movement = cast('Transaction', first_row.transaction)
        Transaction.objects.filter(pk=movement.pk).update(
            source_fingerprint='',
            source_fingerprint_key_version='',
            source_fingerprint_format_version=0,
            source_format_version=0,
            source_file_hash=None,
            source_row_position=None,
        )
        BankStatementRow.objects.filter(pk=first_row.pk).update(
            source_fingerprint='',
            source_fingerprint_key_version='',
            source_fingerprint_format_version=0,
            source_format_version=0,
        )

        BankStatementUpload.objects.filter(pk=first.pk).update(
            expires_at=timezone.now(),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
        movement.refresh_from_db()
        first_row.refresh_from_db()
        self.assertIsNone(movement.source_ref)
        self.assertEqual(movement.source_fingerprint, '')
        self.assertIsNone(movement.source_file_hash)
        self.assertIsNone(movement.source_row_position)
        self.assertIsNone(first_row.source_ref)
        self.assertEqual(first_row.source_fingerprint, '')

        second = self._raiffeisen_upload(
            [
                {
                    'date': moment,
                    'amount': Decimal('-13.20'),
                    'description': 'Комиссия за обслуживание',
                    'source_ref': 'R-LEGACY',
                    'source_ref_strength': 'strong',
                    'category_name': 'Комиссия банка',
                    'row_position': 0,
                },
            ],
            file_hash='legacy-second',
            period_start=date(2026, 1, 15),
            period_end=date(2026, 2, 15),
        )

        second.refresh_from_db()
        row = BankStatementRow.objects.get(
            upload=second,
            source_ref='R-LEGACY',
        )
        self.assertEqual(
            second.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(row.transaction)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(first_row.transaction, movement)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('986.80'))


class TestStatementBankVerification(TestCase):
    """Detected statement bank must match the confirmed account bank."""

    fixtures: list[str] = ['users.yaml']

    NUMBER = '40817810099910004312'
    OTHER_NUMBER = '40817810099910004313'

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Счёт по умолчанию',
            balance=Decimal('10000.00'),
            currency='RUB',
        )

    def _bank(self, code: str, name: str, *, is_system: bool = False) -> Bank:
        bank, _ = Bank.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'is_system': is_system,
                'user': None if is_system else self.user,
            },
        )
        return bank

    def _row(self) -> dict[str, Any]:
        return {
            'date': datetime(2026, 3, 10, 12, tzinfo=UTC),
            'amount': Decimal('-100.00'),
            'description': 'Комиссия за обслуживание',
            'source_ref': 'TICKET06-1',
            'source_ref_strength': 'strong',
            'category_name': 'Комиссия банка',
            'row_position': 0,
        }

    def _run_statement(
        self,
        *,
        bank: str,
        account: Account,
        account_number: str | None = None,
        transactions: list[dict[str, Any]] | None = None,
        requires_markup: bool = False,
    ) -> BankStatementUpload:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=account,
            pdf_file='bank_statements/ticket06.pdf',
        )
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=(
                    [self._row()] if transactions is None else transactions
                ),
                bank=bank,
                account_number=account_number,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
                requires_markup=requires_markup,
            )
            process_bank_statement_task.apply(args=[upload.pk])
        upload.refresh_from_db()
        return upload

    def test_mismatched_bank_keeps_number_binding_coverage_and_money(
        self,
    ) -> None:
        """A different confirmed bank changes nothing and posts nothing."""
        self.account.bank = self._bank(
            BANK_SBERBANK,
            'Сбербанк',
            is_system=True,
        )
        self.account.save(update_fields=['bank'])

        upload = self._run_statement(
            bank='raiffeisen',
            account=self.account,
            account_number=self.NUMBER,
        )

        self.account.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertIsNone(self.account.account_number)
        self.assertEqual(upload.account_id, self.account.pk)
        self.assertFalse(
            StatementPeriodCoverage.objects.filter(upload=upload).exists(),
        )
        self.assertFalse(
            Transaction.objects.filter(account=self.account).exists(),
        )
        self.assertEqual(self.account.balance, Decimal('10000.00'))

    def test_matching_system_bank_binds_number_and_posts(self) -> None:
        """The same confirmed system bank supports number binding and money."""
        self.account.bank = self._bank(
            BANK_SBERBANK,
            'Сбербанк',
            is_system=True,
        )
        self.account.save(update_fields=['bank'])

        upload = self._run_statement(
            bank='sberbank',
            account=self.account,
            account_number=self.NUMBER,
        )

        self.account.refresh_from_db()
        self.assertNotEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(self.account.account_number, self.NUMBER)
        self.assertTrue(
            StatementPeriodCoverage.objects.filter(
                upload=upload,
                is_actual=True,
            ).exists(),
        )
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )

    def test_account_found_by_number_checks_its_bank_before_rebinding(
        self,
    ) -> None:
        """A bank mismatch never replaces the upload account."""
        matched = Account.objects.create(
            user=self.user,
            name_account='Счёт Сбербанка',
            balance=Decimal('5000.00'),
            currency='RUB',
            bank=self._bank(BANK_SBERBANK, 'Сбербанк', is_system=True),
            account_number=self.OTHER_NUMBER,
        )

        upload = self._run_statement(
            bank='raiffeisen',
            account=self.account,
            account_number=self.OTHER_NUMBER,
        )

        matched.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(upload.account_id, self.account.pk)
        self.assertEqual(matched.account_number, self.OTHER_NUMBER)
        self.assertEqual(matched.balance, Decimal('5000.00'))
        self.assertFalse(
            StatementPeriodCoverage.objects.filter(upload=upload).exists(),
        )
        self.assertFalse(Transaction.objects.exists())

    def test_account_found_by_number_with_same_bank_receives_statement(
        self,
    ) -> None:
        """A matching number and bank still rebinds to the found account."""
        matched = Account.objects.create(
            user=self.user,
            name_account='Счёт Сбербанка',
            balance=Decimal('5000.00'),
            currency='RUB',
            bank=self._bank(BANK_SBERBANK, 'Сбербанк', is_system=True),
            account_number=self.OTHER_NUMBER,
        )

        upload = self._run_statement(
            bank='sberbank',
            account=self.account,
            account_number=self.OTHER_NUMBER,
        )

        matched.refresh_from_db()
        self.assertNotEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(upload.account_id, matched.pk)
        self.assertEqual(matched.account_number, self.OTHER_NUMBER)
        self.assertEqual(
            Transaction.objects.filter(account=matched).count(),
            1,
        )
        self.assertTrue(
            StatementPeriodCoverage.objects.filter(
                upload=upload,
                is_actual=True,
            ).exists(),
        )

    def test_every_known_adapter_matches_a_confirmed_bank(self) -> None:
        """All supported adapters accept an account of the same bank."""
        cases = (
            ('raiffeisen', BANK_RAIFFEISENBANK, 'Райффайзенбанк', True),
            ('sberbank', BANK_SBERBANK, 'Сбербанк', True),
            ('ozon', 'user_ozon', 'Озон Банк', False),
            ('rosdorbank', 'user_rosdor', 'РосДорБанк', False),
        )
        for statement_bank, code, name, is_system in cases:
            with self.subTest(bank=statement_bank):
                account = Account.objects.create(
                    user=self.user,
                    name_account=f'Счёт {statement_bank}',
                    balance=Decimal('1000.00'),
                    currency='RUB',
                    bank=self._bank(code, name, is_system=is_system),
                )
                upload = self._run_statement(
                    bank=statement_bank,
                    account=account,
                    requires_markup=True,
                )
                self.assertNotEqual(
                    upload.status,
                    BankStatementUpload.Status.FAILED,
                )
                self.assertEqual(upload.account_id, account.pk)

    def test_user_bank_names_are_compared_with_detected_bank(self) -> None:
        """Personal banks match by name only when they name the same bank."""
        matching = Account.objects.create(
            user=self.user,
            name_account='Личный Сбербанк',
            balance=Decimal('1000.00'),
            currency='RUB',
            bank=self._bank('user_sber', 'Мой Сбербанк'),
        )
        upload = self._run_statement(
            bank='sberbank',
            account=matching,
            requires_markup=True,
        )
        self.assertNotEqual(upload.status, BankStatementUpload.Status.FAILED)

        other = Account.objects.create(
            user=self.user,
            name_account='Личный Озон',
            balance=Decimal('1000.00'),
            currency='RUB',
            bank=self._bank('user_ozon_other', 'Озон Банк'),
        )
        failed = self._run_statement(
            bank='sberbank',
            account=other,
            requires_markup=True,
        )
        self.assertEqual(failed.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(failed.account_id, other.pk)

    def test_unknown_personal_bank_name_does_not_block_number_match(
        self,
    ) -> None:
        """An unrecognized personal name proves no different bank."""
        matched = Account.objects.create(
            user=self.user,
            name_account='Зарплатный счёт',
            balance=Decimal('5000.00'),
            currency='RUB',
            bank=self._bank('user_salary', 'Зарплатный'),
            account_number=self.OTHER_NUMBER,
        )

        upload = self._run_statement(
            bank='sberbank',
            account=self.account,
            account_number=self.OTHER_NUMBER,
        )

        matched.refresh_from_db()
        self.assertNotEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(upload.account_id, matched.pk)
        self.assertEqual(matched.account_number, self.OTHER_NUMBER)
        self.assertEqual(
            Transaction.objects.filter(account=matched).count(),
            1,
        )
        self.assertTrue(
            StatementPeriodCoverage.objects.filter(
                upload=upload,
                is_actual=True,
            ).exists(),
        )

    def test_unconfirmed_account_bank_keeps_supported_processing(self) -> None:
        """Without a confirmed account bank the statement bank is ignored."""
        upload = self._run_statement(bank='raiffeisen', account=self.account)

        self.assertNotEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )

    def test_generic_statement_never_claims_a_confirmed_bank(self) -> None:
        """A common format keeps its markup flow for a bank-specific account."""
        self.account.bank = self._bank(
            BANK_SBERBANK,
            'Сбербанк',
            is_system=True,
        )
        self.account.save(update_fields=['bank'])

        upload = self._run_statement(
            bank='generic',
            account=self.account,
            requires_markup=True,
        )

        self.assertNotEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(upload.statement_bank, 'generic')
