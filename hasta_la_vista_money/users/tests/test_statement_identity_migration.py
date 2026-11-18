"""Historical bank references become private, untrusted fingerprints."""

import importlib
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.statement_id_fingerprint import (
    StatementIdFingerprintService,
)


@override_settings(
    STATEMENT_ID_HMAC_KEYS='{"test-v1":"' + 'ab' * 32 + '"}',
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-v1',
)
class StatementIdentityMigrationTest(TestCase):
    """Migrate identifiers without inferring bank history or moving money."""

    fixtures: list[str] = ['users.yaml']

    @staticmethod
    def _migrate() -> None:
        migration = importlib.import_module(
            'hasta_la_vista_money.users.migrations.'
            '0027_fingerprint_legacy_statement_references',
        )
        migration.fingerprint_legacy_references(
            apps,
            SimpleNamespace(connection=connection),
        )

    @staticmethod
    def _unlinked_row(source_ref: str) -> BankStatementRow:
        account = Account.objects.create(
            user_id=1,
            name_account='Synthetic legacy edge case',
            balance=Decimal('777.00'),
            currency='RUB',
        )
        upload = BankStatementUpload.objects.create(
            user_id=1,
            account=account,
            pdf_file='synthetic.pdf',
        )
        return BankStatementRow.objects.create(
            upload=upload,
            source_ref=source_ref,
        )

    def test_existing_hash_is_preserved_but_not_declared_trusted(self) -> None:
        row = self._unlinked_row('SYNTHETIC-PARTIAL-ID')
        BankStatementRow.objects.filter(pk=row.pk).update(
            source_ref_hash='cd' * 32,
            source_ref_key_id='retired-key',
            source_ref_version=1,
            source_identity_trusted=True,
        )

        self._migrate()

        row.refresh_from_db()
        self.assertIsNone(row.source_ref)
        self.assertEqual(row.source_ref_hash, 'cd' * 32)
        self.assertEqual(row.source_ref_key_id, 'retired-key')
        self.assertEqual(row.source_ref_version, 1)
        self.assertFalse(row.source_identity_trusted)

    def test_migration_v1_is_independent_of_future_runtime_format(self) -> None:
        row = self._unlinked_row('SYNTHETIC-FROZEN-ID')
        with patch.object(
            StatementIdFingerprintService,
            'fingerprint',
            side_effect=RuntimeError('Runtime format changed'),
        ):
            self._migrate()

        row.refresh_from_db()
        expected = StatementIdFingerprintService().fingerprint(
            'legacy-unverified',
            row.upload.account_id,
            'SYNTHETIC-FROZEN-ID',
        )
        self.assertEqual(row.source_ref_hash, expected.digest)

    def test_whitespace_only_id_is_removed_without_inventing_identity(
        self,
    ) -> None:
        row = self._unlinked_row(' \t ')
        with override_settings(
            STATEMENT_ID_HMAC_KEYS='',
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='',
        ):
            self._migrate()

        row.refresh_from_db()
        self.assertIsNone(row.source_ref)
        self.assertIsNone(row.source_ref_hash)
        self.assertFalse(row.source_identity_trusted)

    def test_padded_legacy_ids_do_not_merge_financial_movements(self) -> None:
        row = self._unlinked_row('SYNTHETIC-PADDED-ID')
        category = Category.objects.create(
            user_id=1,
            name='Synthetic padded references',
            type='expense',
        )
        for reference in ('SYNTHETIC-PADDED-ID', ' SYNTHETIC-PADDED-ID '):
            Transaction.objects.create(
                user_id=1,
                account=row.upload.account,
                category=category,
                type='expense',
                amount=Decimal('12.50'),
                date=timezone.now(),
                source_ref=reference,
            )

        self._migrate()

        movements = Transaction.objects.filter(account=row.upload.account)
        self.assertEqual(movements.count(), 2)
        self.assertFalse(movements.exclude(source_ref=None).exists())
        self.assertFalse(
            movements.filter(source_identity_trusted=True).exists(),
        )
        self.assertEqual(
            len(set(movements.values_list('source_ref_hash', flat=True))),
            1,
        )
        row.upload.account.refresh_from_db()
        self.assertEqual(row.upload.account.balance, Decimal('777.00'))

    @override_settings(
        STATEMENT_ID_HMAC_KEYS='',
        STATEMENT_ID_HMAC_ACTIVE_KEY_ID='',
    )
    def test_missing_key_preserves_raw_identifiers_and_money(self) -> None:
        account = Account.objects.create(
            user_id=1,
            name_account='Synthetic missing-key account',
            balance=Decimal('777.00'),
            currency='RUB',
        )
        upload = BankStatementUpload.objects.create(
            user_id=1,
            account=account,
            pdf_file='synthetic.pdf',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_ref='SYNTHETIC-UNHASHED-ID',
            decision=BankStatementRow.Decision.DEFERRED,
        )
        migration = importlib.import_module(
            'hasta_la_vista_money.users.migrations.'
            '0027_fingerprint_legacy_statement_references',
        )
        audit_count = AuditLog.objects.count()

        with self.assertRaises(ImproperlyConfigured):
            migration.fingerprint_legacy_references(
                apps,
                SimpleNamespace(connection=connection),
            )

        row.refresh_from_db()
        account.refresh_from_db()
        self.assertEqual(row.source_ref, 'SYNTHETIC-UNHASHED-ID')
        self.assertIsNone(row.source_ref_hash)
        self.assertEqual(row.decision, BankStatementRow.Decision.DEFERRED)
        self.assertEqual(account.balance, Decimal('777.00'))
        self.assertEqual(AuditLog.objects.count(), audit_count)

    def test_deleted_movement_audit_loses_only_raw_bank_reference(self) -> None:
        audit = AuditLog.objects.create(
            user_id=1,
            model_name='transactions.Transaction',
            object_pk='deleted-synthetic-movement',
            action='delete',
            diff={
                'source_ref': {'old': 'SYNTHETIC-DELETED-ID', 'new': None},
                'amount': {'old': '12.50', 'new': None},
            },
        )
        timestamp = audit.created_at
        migration = importlib.import_module(
            'hasta_la_vista_money.users.migrations.'
            '0027_fingerprint_legacy_statement_references',
        )

        migration.fingerprint_legacy_references(
            apps,
            SimpleNamespace(connection=connection),
        )

        audit.refresh_from_db()
        self.assertNotIn('SYNTHETIC-DELETED-ID', str(audit.diff))
        self.assertEqual(audit.diff['amount']['old'], '12.50')
        self.assertEqual(audit.created_at, timestamp)
        self.assertEqual(audit.user_id, 1)
        self.assertEqual(audit.action, 'delete')
        self.assertTrue(
            AuditLog.objects.exclude(pk=audit.pk)
            .filter(
                user_id=1,
                diff__bank_identifiers_anonymized__new=True,
            )
            .exists(),
        )

    def test_legacy_row_and_movement_share_untrusted_fingerprint(self) -> None:
        user = User.objects.get(pk=1)
        account = Account.objects.create(
            user=user,
            name_account='Synthetic migration account',
            balance=Decimal('777.00'),
            currency='RUB',
        )
        category = Category.objects.create(
            user=user,
            name='Synthetic migration category',
            type='expense',
        )
        movement = Transaction.objects.create(
            user=user,
            account=account,
            category=category,
            type='expense',
            amount=Decimal('12.50'),
            date=timezone.now(),
            source_ref='SYNTHETIC-ID-17',
        )
        upload = BankStatementUpload.objects.create(
            user=user,
            account=account,
            pdf_file='synthetic.pdf',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction=movement,
            source_ref='SYNTHETIC-ID-17',
            source_row_position=4,
            decision=BankStatementRow.Decision.NEW,
        )
        migration = importlib.import_module(
            'hasta_la_vista_money.users.migrations.'
            '0027_fingerprint_legacy_statement_references',
        )

        migration.fingerprint_legacy_references(
            apps,
            SimpleNamespace(connection=connection),
        )

        row.refresh_from_db()
        movement.refresh_from_db()
        account.refresh_from_db()
        expected = StatementIdFingerprintService().fingerprint(
            'legacy-unverified',
            account.pk,
            'SYNTHETIC-ID-17',
        )
        self.assertIsNone(row.source_ref)
        self.assertIsNone(movement.source_ref)
        self.assertEqual(row.source_ref_hash, expected.digest)
        self.assertEqual(movement.source_ref_hash, expected.digest)
        self.assertEqual(row.source_ref_key_id, 'test-v1')
        self.assertFalse(row.source_identity_trusted)
        self.assertFalse(movement.source_identity_trusted)
        self.assertEqual(row.transaction_id, movement.pk)
        self.assertEqual(row.source_row_position, 4)
        self.assertEqual(account.balance, Decimal('777.00'))
        self.assertEqual(movement.amount, Decimal('12.50'))
        self.assertEqual(Transaction.objects.count(), 1)

        # A second run needs no key and never hashes an existing HMAC again.
        audit_count = AuditLog.objects.count()
        with override_settings(
            STATEMENT_ID_HMAC_KEYS='',
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='',
        ):
            migration.fingerprint_legacy_references(
                apps,
                SimpleNamespace(connection=connection),
            )
        movement.refresh_from_db()
        self.assertEqual(movement.source_ref_hash, expected.digest)
        self.assertEqual(AuditLog.objects.count(), audit_count)


@override_settings(
    STATEMENT_ID_HMAC_KEYS='{"test-v1":"' + 'ab' * 32 + '"}',
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-v1',
)
class StatementIdentityMigrationReplayTest(TransactionTestCase):
    """Apply historical models and roll back schema on synthetic PostgreSQL."""

    def test_populated_forward_and_schema_rollback_preserve_money(self) -> None:
        old = ('users', '0026_bankstatementrow_data_cleaned_at_and_more')
        new = ('users', '0027_fingerprint_legacy_statement_references')
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        original_leaf_nodes = executor.loader.graph.leaf_nodes()
        old_apps = executor.loader.project_state(
            [
                old,
                (
                    'transactions',
                    '0007_transaction_source_identity_trusted_and_more',
                ),
                ('system', '0007_statement_markup'),
            ],
        ).apps
        try:
            user = old_apps.get_model('users', 'User').objects.create(
                username='synthetic-historical-migration',
            )
            account_model = old_apps.get_model('finance_account', 'Account')
            account = account_model.objects.create(
                user=user,
                name_account='Synthetic historical migration',
                balance=Decimal('777.00'),
                currency='RUB',
            )
            category = old_apps.get_model(
                'transactions',
                'Category',
            ).objects.create(
                user=user,
                name='Synthetic historical category',
                type='expense',
            )
            movement_model = old_apps.get_model('transactions', 'Transaction')
            movement = movement_model.objects.create(
                user=user,
                account=account,
                category=category,
                type='expense',
                amount=Decimal('12.50'),
                date=timezone.now(),
                source_ref='SYNTHETIC-HISTORICAL-ID',
            )

            MigrationExecutor(connection).migrate([new])

            movement.refresh_from_db()
            self.assertIsNone(movement.source_ref)
            self.assertEqual(len(movement.source_ref_hash), 64)
            self.assertFalse(movement.source_identity_trusted)
            self.assertEqual(movement.amount, Decimal('12.50'))
            self.assertEqual(
                account_model.objects.get(pk=account.pk).balance,
                Decimal('777.00'),
            )

            original_leaf_nodes = MigrationExecutor(
                connection,
            ).loader.graph.leaf_nodes()
            MigrationExecutor(connection).migrate(
                [('users', '0025_statement_row_defer_exclude')],
            )

            movement.refresh_from_db()
            self.assertIsNone(movement.source_ref)
            self.assertEqual(movement.amount, Decimal('12.50'))
            self.assertEqual(movement_model.objects.count(), 1)
            self.assertEqual(
                account_model.objects.get(pk=account.pk).balance,
                Decimal('777.00'),
            )
        finally:
            MigrationExecutor(connection).migrate(original_leaf_nodes or [new])
