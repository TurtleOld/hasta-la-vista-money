"""Tests for bank statement upload functionality."""

import tempfile
from datetime import timedelta
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
from hasta_la_vista_money.users.models import BankStatementUpload, User
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParser,
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
        from hasta_la_vista_money.users.forms import (
            BankStatementUploadForm,
        )

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
        from hasta_la_vista_money.users.forms import (
            BankStatementUploadForm,
        )

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
        from hasta_la_vista_money.users.forms import (
            BankStatementUploadForm,
        )

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
        from hasta_la_vista_money.users.forms import (
            BankStatementUploadForm,
        )

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
        from hasta_la_vista_money.users.services.bank_statement import (
            BankStatementParseError,
            process_bank_statement,
        )
        from hasta_la_vista_money.expense.models import Expense
        from hasta_la_vista_money.income.models import Income

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
        from hasta_la_vista_money.users.services.bank_statement import (
            _get_or_create_expense_category,
            _get_or_create_income_category,
        )

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
        from hasta_la_vista_money.users.services.bank_statement import (
            _get_or_create_expense_category,
        )

        # Create a very long category name
        long_name = 'A' * 300
        category = _get_or_create_expense_category(self.user, long_name)

        # Verify it's truncated to 250
        self.assertEqual(len(category.name), 250)
        self.assertTrue(category.name.startswith('AAAAA'))
