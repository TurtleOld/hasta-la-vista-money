"""Legacy EXPIRED rows get the cleaned-data marker without inventing data."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import StateApps
from django.test import TransactionTestCase
from django.utils import timezone

from hasta_la_vista_money.users.models import BankStatementRow
from hasta_la_vista_money.users.services.statement_retention_policy import (
    row_has_bank_data,
)
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    statement_identity_settings,
)

TRANSACTIONS_STATE = (
    'transactions',
    '0007_transaction_source_identity_trusted_and_more',
)
MIGRATE_FROM = [
    ('users', '0025_statement_row_defer_exclude'),
    TRANSACTIONS_STATE,
]
MIGRATE_TO = [
    ('users', '0026_bankstatementrow_data_cleaned_at_and_more'),
    TRANSACTIONS_STATE,
]


@statement_identity_settings
class LegacyExpiredCleanupMarkerMigrationTest(TransactionTestCase):
    """A historic EXPIRED row becomes unavailable without inventing history."""

    migrate_from = MIGRATE_FROM
    migrate_to = MIGRATE_TO

    def setUp(self) -> None:
        self.executor = MigrationExecutor(transaction.get_connection())
        self.executor.migrate(self.migrate_from)
        old_apps = self.executor.loader.project_state(self.migrate_from).apps
        user_model = old_apps.get_model('users', 'User')
        account_model = old_apps.get_model('finance_account', 'Account')
        category_model = old_apps.get_model('transactions', 'Category')
        transaction_model = old_apps.get_model('transactions', 'Transaction')
        upload_model = old_apps.get_model('users', 'BankStatementUpload')
        row_model = old_apps.get_model('users', 'BankStatementRow')

        self.historic_cleaned_at = datetime(
            2026,
            2,
            1,
            10,
            0,
            tzinfo=timezone.get_current_timezone(),
        )
        self.user = user_model.objects.create(username='legacy-expired')
        self.account = account_model.objects.create(
            user_id=self.user.pk,
            name_account='Старый банк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.category = category_model.objects.create(
            user_id=self.user.pk,
            name='Старая еда',
            type='expense',
        )
        self.moment = datetime(
            2026,
            1,
            15,
            12,
            0,
            tzinfo=timezone.get_current_timezone(),
        )
        self.movement = transaction_model.objects.create(
            user_id=self.user.pk,
            account_id=self.account.pk,
            category_id=self.category.pk,
            type='expense',
            amount=Decimal('100.00'),
            date=self.moment,
        )
        self.cleaned_upload = upload_model.objects.create(
            user_id=self.user.pk,
            account_id=self.account.pk,
            pdf_file='',
            expires_at=self.historic_cleaned_at + timedelta(days=30),
            retention_cleaned_at=self.historic_cleaned_at,
        )
        self.unknown_time_upload = upload_model.objects.create(
            user_id=self.user.pk,
            account_id=self.account.pk,
            pdf_file='',
            expires_at=self.historic_cleaned_at + timedelta(days=30),
            retention_cleaned_at=None,
        )
        self.future_upload = upload_model.objects.create(
            user_id=self.user.pk,
            account_id=self.account.pk,
            pdf_file='',
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.cleaned_expired = row_model.objects.create(
            upload_id=self.cleaned_upload.pk,
            transaction_id=self.movement.pk,
            decision='expired',
            source_row_position=5,
        )
        self.unknown_time_expired = row_model.objects.create(
            upload_id=self.unknown_time_upload.pk,
            decision='expired',
            source_row_position=6,
        )
        self.future_expired = row_model.objects.create(
            upload_id=self.future_upload.pk,
            decision='expired',
            source_row_position=7,
        )
        self.residual_payload = row_model.objects.create(
            upload_id=self.future_upload.pk,
            decision='expired',
            amount=Decimal('25.00'),
            description='Секретная строка',
            source_ref='legacy-raw-ref',
            source_row_position=8,
        )
        self.pending_row = row_model.objects.create(
            upload_id=self.future_upload.pk,
            decision='pending',
            source_row_position=9,
        )

    def tearDown(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _migrate(self, targets: list[tuple[str, str]]) -> StateApps:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def _migrate_to_leaf(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_migration_marks_only_cleaned_expired_rows(self) -> None:
        new_apps = self._migrate(self.migrate_to)
        row_model = new_apps.get_model('users', 'BankStatementRow')
        transaction_model = new_apps.get_model('transactions', 'Transaction')

        cleaned = row_model.objects.get(pk=self.cleaned_expired.pk)
        self.assertEqual(cleaned.data_cleaned_at, self.historic_cleaned_at)
        self.assertEqual(cleaned.decision, 'expired')
        self.assertEqual(
            cleaned.transaction_id,
            self.movement.pk,
        )
        self.assertEqual(cleaned.source_row_position, 5)

        unknown_time = row_model.objects.get(pk=self.unknown_time_expired.pk)
        self.assertIsNotNone(unknown_time.data_cleaned_at)
        self.assertEqual(unknown_time.decision, 'expired')

        future_expired = row_model.objects.get(pk=self.future_expired.pk)
        self.assertIsNotNone(future_expired.data_cleaned_at)

        residual = row_model.objects.get(pk=self.residual_payload.pk)
        self.assertIsNone(residual.data_cleaned_at)
        self.assertEqual(residual.amount, Decimal('25.00'))
        self.assertEqual(residual.description, 'Секретная строка')
        self.assertEqual(residual.source_ref, 'legacy-raw-ref')

        pending = row_model.objects.get(pk=self.pending_row.pk)
        self.assertIsNone(pending.data_cleaned_at)

        movement = transaction_model.objects.get(pk=self.movement.pk)
        self.assertEqual(movement.amount, Decimal('100.00'))
        self.assertEqual(movement.date, self.moment)

    def test_marked_row_is_unavailable_even_with_future_upload(self) -> None:
        self._migrate(self.migrate_to)
        self._migrate_to_leaf()

        cleaned = BankStatementRow.objects.get(pk=self.cleaned_expired.pk)
        future_expired = BankStatementRow.objects.get(
            pk=self.future_expired.pk,
        )
        residual = BankStatementRow.objects.get(pk=self.residual_payload.pk)

        self.assertFalse(row_has_bank_data(cleaned))
        self.assertFalse(row_has_bank_data(future_expired))
        self.assertTrue(row_has_bank_data(residual))

    def test_migration_reverses_without_touching_rows(self) -> None:
        self._migrate(self.migrate_to)

        old_apps = self._migrate(self.migrate_from)
        row_model = old_apps.get_model('users', 'BankStatementRow')

        self.assertEqual(row_model.objects.count(), 5)
