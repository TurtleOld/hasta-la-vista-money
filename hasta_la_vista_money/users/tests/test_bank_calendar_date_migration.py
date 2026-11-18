"""Bank calendar day metadata migrates without moving money or dates."""

from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import StateApps
from django.test import TransactionTestCase
from django.utils import timezone


class BankCalendarDateMigrationTest(TransactionTestCase):
    """Adding the nullable bank day keeps existing financial data intact."""

    migrate_from = [
        ('users', '0029_bankstatementrow_date_precision_and_more'),
        (
            'transactions',
            '0007_transaction_source_identity_trusted_and_more',
        ),
        ('finance_account', '0026_account_account_number'),
    ]
    migrate_to = [
        ('users', '0030_bankstatementrow_bank_calendar_date'),
        ('transactions', '0008_transaction_bank_calendar_date'),
        ('finance_account', '0027_transfermoneylog_bank_calendar_date'),
    ]

    def setUp(self) -> None:
        self.executor = MigrationExecutor(transaction.get_connection())
        self.executor.migrate(self.migrate_from)
        old_apps = self.executor.loader.project_state(self.migrate_from).apps
        user_model = old_apps.get_model('users', 'User')
        account_model = old_apps.get_model('finance_account', 'Account')
        category_model = old_apps.get_model('transactions', 'Category')
        transaction_model = old_apps.get_model('transactions', 'Transaction')
        transfer_model = old_apps.get_model(
            'finance_account',
            'TransferMoneyLog',
        )
        upload_model = old_apps.get_model('users', 'BankStatementUpload')
        row_model = old_apps.get_model('users', 'BankStatementRow')

        self.user = user_model.objects.create(username='bank-day-migration')
        self.account = account_model.objects.create(
            user_id=self.user.pk,
            name_account='Legacy bank',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.category = category_model.objects.create(
            user_id=self.user.pk,
            name='Legacy food',
            type='expense',
        )
        self.moment = datetime(
            2026,
            5,
            4,
            12,
            30,
            tzinfo=timezone.get_current_timezone(),
        )
        self.transaction = transaction_model.objects.create(
            user_id=self.user.pk,
            account_id=self.account.pk,
            category_id=self.category.pk,
            type='expense',
            amount=Decimal('100.00'),
            date=self.moment,
        )
        self.transfer = transfer_model.objects.create(
            user_id=self.user.pk,
            from_account_id=self.account.pk,
            to_account_id=self.account.pk,
            amount=Decimal('250.00'),
            exchange_date=self.moment,
        )
        self.upload = upload_model.objects.create(
            user_id=self.user.pk,
            account_id=self.account.pk,
            pdf_file='legacy.pdf',
        )
        self.row = row_model.objects.create(
            upload_id=self.upload.pk,
            transaction_id=self.transaction.pk,
            transaction_date=self.moment,
            amount=Decimal('25.00'),
            date_precision='day',
            decision='deferred',
            source_row_position=3,
        )

    def tearDown(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _migrate(self, targets: list[tuple[str, str]]) -> StateApps:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def test_forward_and_backward_keep_dates_money_and_null_metadata(
        self,
    ) -> None:
        new_apps = self._migrate(self.migrate_to)
        transaction_model = new_apps.get_model('transactions', 'Transaction')
        transfer_model = new_apps.get_model(
            'finance_account',
            'TransferMoneyLog',
        )
        row_model = new_apps.get_model('users', 'BankStatementRow')

        transaction_row = transaction_model.objects.get(pk=self.transaction.pk)
        self.assertIsNone(transaction_row.bank_calendar_date)
        self.assertEqual(transaction_row.amount, Decimal('100.00'))
        self.assertEqual(transaction_row.date, self.moment)

        transfer_row = transfer_model.objects.get(pk=self.transfer.pk)
        self.assertIsNone(transfer_row.bank_calendar_date)
        self.assertEqual(transfer_row.amount, Decimal('250.00'))
        self.assertEqual(transfer_row.exchange_date, self.moment)

        statement_row = row_model.objects.get(pk=self.row.pk)
        self.assertIsNone(statement_row.bank_calendar_date)
        self.assertEqual(statement_row.transaction_date, self.moment)
        self.assertEqual(statement_row.amount, Decimal('25.00'))
        self.assertEqual(statement_row.date_precision, 'day')
        self.assertEqual(statement_row.transaction_id, self.transaction.pk)

        old_apps = self._migrate(self.migrate_from)
        old_transaction = old_apps.get_model('transactions', 'Transaction')
        old_transfer = old_apps.get_model(
            'finance_account',
            'TransferMoneyLog',
        )
        old_row = old_apps.get_model('users', 'BankStatementRow')

        transaction_row = old_transaction.objects.get(pk=self.transaction.pk)
        self.assertEqual(transaction_row.date, self.moment)
        self.assertEqual(transaction_row.amount, Decimal('100.00'))
        transfer_row = old_transfer.objects.get(pk=self.transfer.pk)
        self.assertEqual(transfer_row.exchange_date, self.moment)
        self.assertEqual(transfer_row.amount, Decimal('250.00'))
        statement_row = old_row.objects.get(pk=self.row.pk)
        self.assertEqual(statement_row.date_precision, 'day')
        self.assertEqual(statement_row.transaction_id, self.transaction.pk)
        self.assertEqual(statement_row.amount, Decimal('25.00'))
        self.assertNotIn(
            'bank_calendar_date',
            {field.name for field in old_row._meta.get_fields()},
        )
