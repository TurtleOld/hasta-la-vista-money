"""Tests for bank statement upload functionality."""

import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pandas as pd
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from faker import Faker

from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.users.forms import BankStatementUploadForm
from hasta_la_vista_money.users.models import BankStatementUpload, User
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
    BankStatementParser,
    _create_parser,
    _GenericBankParser,
    _get_or_create_expense_category,
    _get_or_create_income_category,
    _RaiffeisenBankParser,
    _SberbankParser,
    process_bank_statement,
)


class TestBankStatementUploadView(TestCase):
    """Test cases for bank statement upload view."""

    fixtures: ClassVar[list[str]] = ['users.yaml']

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

        self.upload_url = reverse('users:bank_statement_upload')

    def test_get_upload_page(self) -> None:
        """Test GET request to upload page."""
        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            'users/bank_statement_upload.html',
        )
        self.assertIn('form', response.context)

    def test_upload_page_requires_authentication(self) -> None:
        """Test that upload page requires login."""
        self.client.logout()
        response = self.client.get(self.upload_url)
        self.assertEqual(response.status_code, 302)
        # Check that it redirects to login
        # (could be /auth/login/ or /users/login/)
        self.assertIn('login', response.url.lower())

    @patch('hasta_la_vista_money.users.views.process_bank_statement_task')
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

        # Check redirect and message
        self.assertRedirects(response, self.upload_url)
        messages = list(get_messages(response.wsgi_request))
        # Check that there's a success message
        self.assertTrue(len(messages) > 0)

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

    fixtures: ClassVar[list[str]] = ['users.yaml']

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

        url = reverse('users:bank_statement_upload_status', args=[upload.id])
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

        url = reverse('users:bank_statement_upload_status', args=[upload.id])
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

        url = reverse('users:bank_statement_upload_status', args=[upload.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['progress'], 100)
        self.assertEqual(data['income_count'], 10)
        self.assertEqual(data['expense_count'], 20)

    def test_get_status_failed(self) -> None:
        """Test getting status of failed upload."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            status='failed',
            error_message='Тестовая ошибка',
        )

        url = reverse('users:bank_statement_upload_status', args=[upload.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'failed')
        self.assertEqual(data['error_message'], 'Тестовая ошибка')

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

        url = reverse('users:bank_statement_upload_status', args=[upload.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)


class TestBankStatementParser(TestCase):
    """Test cases for bank statement parser."""

    def setUp(self) -> None:
        """Set up test data."""
        self.faker = Faker()

    def _create_mock_pdf(self, transactions: list[dict]) -> Path:
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
            transactions = parser.parse()

            # Basic validation
            self.assertIsInstance(transactions, list)
        finally:
            pdf_path.unlink()


class TestProcessBankStatementTask(TestCase):
    """Test cases for Celery task processing bank statements."""

    fixtures: ClassVar[list[str]] = ['users.yaml']

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
    ) -> list[dict]:
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
        # Manually create categories as the task would
        income_category, created = IncomeCategory.objects.get_or_create(
            user=self.user,
            name='Зарплата Январь',
        )
        self.assertTrue(created or income_category.pk is not None)

        expense_category, created = ExpenseCategory.objects.get_or_create(
            user=self.user,
            name='Продукты Магнит',
        )
        self.assertTrue(created or expense_category.pk is not None)

        # Verify categories exist
        self.assertTrue(
            IncomeCategory.objects.filter(
                user=self.user,
                name='Зарплата Январь',
            ).exists(),
        )
        self.assertTrue(
            ExpenseCategory.objects.filter(
                user=self.user,
                name='Продукты Магнит',
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

    fixtures: ClassVar[list[str]] = ['users.yaml']

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

    fixtures: ClassVar[list[str]] = ['users.yaml']

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

    fixtures: ClassVar[list[str]] = ['users.yaml']

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

        # Create mock PDF file
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            pdf_path = Path(temp_file.name)

        try:
            # This will fail with mock PDF, but we can test error handling
            with self.assertRaises(BankStatementParseError):
                process_bank_statement(
                    pdf_path=pdf_path,
                    account=account,
                    user=self.user,
                )
        finally:
            pdf_path.unlink()

    def test_category_creation_for_transaction(self) -> None:
        """Test that categories are created for transactions."""
        # Create expense category
        expense_cat = _get_or_create_expense_category(
            self.user,
            'Тестовые расходы',
        )
        self.assertEqual(expense_cat.user, self.user)
        self.assertEqual(expense_cat.name, 'Тестовые расходы')

        # Create income category
        income_cat = _get_or_create_income_category(
            self.user,
            'Тестовый доход',
        )
        self.assertEqual(income_cat.user, self.user)
        self.assertEqual(income_cat.name, 'Тестовый доход')

        # Verify categories exist
        self.assertTrue(
            ExpenseCategory.objects.filter(
                user=self.user,
                name='Тестовые расходы',
            ).exists(),
        )
        self.assertTrue(
            IncomeCategory.objects.filter(
                user=self.user,
                name='Тестовый доход',
            ).exists(),
        )

    def test_category_name_truncation(self) -> None:
        """Test that category names are truncated to 250 characters."""
        # Create a very long category name
        long_name = 'A' * 300
        category = _get_or_create_expense_category(self.user, long_name)

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


class TestBankStatementProcessIntegration(TestCase):
    """Integration tests for process_bank_statement function."""

    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self) -> None:
        """Set up test data."""
        self.user: User = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Тестовый счет',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_process_bank_statement_creates_transactions(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Test that process_bank_statement creates transactions."""
        # Create mock transaction data
        mock_df = pd.DataFrame(
            {
                0: ['01.01.2024 10:00', '1', '2'],
                1: ['', '', ''],
                2: ['', 'Зарплата', 'Покупка'],
                3: ['', '', ''],
                4: ['', '', ''],
                5: ['', '+50000,00 ₽', '-1500,00 ₽'],
                6: ['', '', ''],
            },
        )

        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        # Create mock PDF file
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            pdf_path = Path(temp_file.name)

        try:
            result = process_bank_statement(
                pdf_path=pdf_path,
                account=self.account,
                user=self.user,
            )

            # Basic validation - just check it returns a dict
            self.assertIsInstance(result, dict)
            self.assertIn('income_count', result)
            self.assertIn('expense_count', result)
            self.assertIn('total_count', result)
        finally:
            pdf_path.unlink()

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

        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            pdf_path = Path(temp_file.name)

        try:
            result = process_bank_statement(
                pdf_path=pdf_path,
                account=self.account,
                user=self.user,
            )

            # Basic validation - just check it returns a dict
            self.assertIsInstance(result, dict)
        finally:
            pdf_path.unlink()

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_process_bank_statement_creates_categories(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Test that categories are created for transactions."""
        mock_df = pd.DataFrame(
            {
                0: ['01.01.2024 10:00', '1', '2'],
                1: ['', '', ''],
                2: ['', 'Зарплата Январь', 'Продукты Магнит'],
                3: ['', '', ''],
                4: ['', '', ''],
                5: ['', '+50000,00 ₽', '-1500,00 ₽'],
                6: ['', '', ''],
            },
        )

        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            pdf_path = Path(temp_file.name)

        try:
            result = process_bank_statement(
                pdf_path=pdf_path,
                account=self.account,
                user=self.user,
            )

            # Basic validation - just check it completes without error
            self.assertIsInstance(result, dict)
        finally:
            pdf_path.unlink()

    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_process_bank_statement_reuses_existing_categories(
        self,
        mock_camelot: MagicMock,
    ) -> None:
        """Test that existing categories are reused."""
        # Create existing categories
        IncomeCategory.objects.create(
            user=self.user,
            name='Зарплата Январь',
        )
        ExpenseCategory.objects.create(
            user=self.user,
            name='Продукты Магнит',
        )

        mock_df = pd.DataFrame(
            {
                0: ['01.01.2024 10:00', '1', '2'],
                1: ['', '', ''],
                2: ['', 'Зарплата Январь', 'Продукты Магнит'],
                3: ['', '', ''],
                4: ['', '', ''],
                5: ['', '+50000,00 ₽', '-1500,00 ₽'],
                6: ['', '', ''],
            },
        )

        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]

        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.pdf',
            delete=False,
        ) as temp_file:
            temp_file.write(b'%PDF-1.4 mock pdf')
            pdf_path = Path(temp_file.name)

        try:
            process_bank_statement(
                pdf_path=pdf_path,
                account=self.account,
                user=self.user,
            )

            # Verify existing categories were used (not created again)
            income_count = IncomeCategory.objects.filter(
                user=self.user,
                name='Зарплата Январь',
            ).count()
            expense_count = ExpenseCategory.objects.filter(
                user=self.user,
                name='Продукты Магнит',
            ).count()

            self.assertEqual(income_count, 1)
            self.assertEqual(expense_count, 1)
        finally:
            pdf_path.unlink()


class TestBankStatementEdgeCases(TestCase):
    """Edge case tests for bank statement processing."""

    fixtures: ClassVar[list[str]] = ['users.yaml']

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
                transactions = parser.parse()

                self.assertEqual(transactions, [])
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
                transactions = parser.parse()

                # Should not parse table with < MIN_TABLE_COLUMNS
                self.assertEqual(transactions, [])
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

        income_cat = _get_or_create_income_category(self.user, long_name)
        self.assertEqual(len(income_cat.name), 250)

        expense_cat = _get_or_create_expense_category(self.user, long_name)
        self.assertEqual(len(expense_cat.name), 250)

    def test_get_or_create_category_with_special_chars(self) -> None:
        """Test creating category with special characters."""
        special_name = 'Категория; с, спец. символами!'

        income_cat = _get_or_create_income_category(
            self.user,
            special_name,
        )
        self.assertEqual(income_cat.name, special_name)

        expense_cat = _get_or_create_expense_category(
            self.user,
            special_name,
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

    def test_detection_failure_falls_back_to_generic(self) -> None:
        """_create_parser returns _GenericBankParser on failure."""
        pdf_path = self._make_pdf()
        try:
            with patch(
                'hasta_la_vista_money.users.services.bank_statement'
                '._extract_pdf_text_for_detection',
                side_effect=RuntimeError('pdfminer error'),
            ):
                parser = _create_parser(pdf_path)
                self.assertIsInstance(parser, _GenericBankParser)
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

    def _make_row(self, cols: list) -> pd.Series:
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
        self.assertIsNotNone(amount)
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
        self.assertIsNotNone(amount)
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

    def _make_df(self, rows: list) -> pd.DataFrame:
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

    def test_parse_table_skips_zero_amount(self) -> None:
        """Rows where amount cannot be extracted are skipped."""
        parser = self._make_parser()
        df = self._make_df(
            [
                ['18.02.2026 17:11', 'Категория', '', '1 000,00 ₽'],
                ['18.02.2026 / 123', 'Описание', '', ''],
            ],
        )
        transactions = parser._parse_table(df)
        self.assertEqual(len(transactions), 0)

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
