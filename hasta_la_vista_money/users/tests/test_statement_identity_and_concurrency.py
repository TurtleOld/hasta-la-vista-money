"""Statement identity, canonical duplicates, and atomic balance behaviour."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Barrier, Event, Thread
from typing import Any, cast
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Model
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import ACCOUNT_TYPE_CREDIT_CARD
from hasta_la_vista_money.finance_account.models import (
    Account,
    StatementPeriodCoverage,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.transactions.commands import UpdateTransactionCommand
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.bank_statement import (
    StatementParseResult,
)
from hasta_la_vista_money.users.services.bank_statement_import import (
    FALLBACK_CATEGORY,
    BankStatementImportService,
    StatementImportResult,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
    ReconciliationDecisionConflictError,
    StaleStatementCandidateError,
)
from hasta_la_vista_money.users.services.statement_coverage import (
    StatementCoverageService,
)
from hasta_la_vista_money.users.services.statement_identity import (
    StatementFingerprintUnavailableError,
    StatementIdentityService,
)
from hasta_la_vista_money.users.services.statement_markup import (
    StatementMarkupConflictError,
)
from hasta_la_vista_money.users.tasks import process_bank_statement_task

WHEN = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
KEYS = {'k1': 'first-test-secret', 'k2': 'second-test-secret'}
# Explicit synthetic namespace: production banks keep their own policy and
# the generic bank has no bank identity to fingerprint.
SYNTHETIC_BANK = 'synthetic-test'
# The import classifies a row before its write transaction, so acting on
# the second call pauses the run with the first row already posted.
PAUSE_BEFORE_SECOND_ROW = 2


def _signal_before_movement_lock(
    decision_started: Event,
) -> Callable[..., Any]:
    """Announce the movement lock only when its own SQL is about to run.

    The candidate is read by a plain ``SELECT`` before the movement is
    re-read with ``SELECT ... FOR UPDATE``; signalling at method entry
    would let the holder commit first and the movement read would then
    fail without ever waiting on the lock.
    """
    movement_tables = (
        Transaction._meta.db_table,
        TransferMoneyLog._meta.db_table,
    )

    def wrapper(
        execute: Callable[..., Any],
        sql: str,
        params: Any,
        many: bool,
        context: dict[str, Any],
    ) -> Any:
        if 'FOR UPDATE' in sql and any(
            table in sql for table in movement_tables
        ):
            decision_started.set()
        return execute(sql, params, many, context)

    return wrapper


class StatementFingerprintTest(TestCase):
    """HMAC fingerprints carry bank/account and key/format versions."""

    def test_fingerprint_context_and_versions_change_the_digest(self) -> None:
        service = StatementIdentityService(
            keys=KEYS,
            active_key_version='k2',
            format_version=3,
        )

        base = service.fingerprint(
            bank=SYNTHETIC_BANK,
            account_id=1,
            source_ref='doc-1',
        )
        self.assertEqual(len(base.digest), 64)
        self.assertNotEqual(base.digest, 'doc-1')
        self.assertEqual(base.key_version, 'k2')
        self.assertEqual(base.format_version, 3)

        self.assertNotEqual(
            base.digest,
            service.fingerprint(
                bank='sberbank',
                account_id=1,
                source_ref='doc-1',
            ).digest,
        )
        self.assertNotEqual(
            base.digest,
            service.fingerprint(
                bank=SYNTHETIC_BANK,
                account_id=2,
                source_ref='doc-1',
            ).digest,
        )

    def test_rotation_writes_active_key_and_recognizes_old_keys(self) -> None:
        service = StatementIdentityService(
            keys=KEYS,
            active_key_version='k2',
            format_version=1,
        )
        written = service.fingerprint(
            bank=SYNTHETIC_BANK,
            account_id=1,
            source_ref='doc-1',
        )
        recognized = service.recognition(
            bank=SYNTHETIC_BANK,
            account_id=1,
            source_ref='doc-1',
        )

        self.assertEqual(written.key_version, 'k2')
        self.assertIn(written, recognized)
        self.assertIn('k1', {item.key_version for item in recognized})

    def test_missing_configuration_and_lost_key_are_explicit(self) -> None:
        unconfigured = StatementIdentityService(
            keys={},
            active_key_version='',
        )
        self.assertFalse(unconfigured.is_configured)
        with self.assertRaises(StatementFingerprintUnavailableError):
            unconfigured.fingerprint(
                bank=SYNTHETIC_BANK,
                account_id=1,
                source_ref='doc-1',
            )

        rotated = StatementIdentityService(
            keys={'k2': 'second-test-secret'},
            active_key_version='k2',
            format_version=1,
        )
        self.assertEqual(rotated.missing_keys({'k1', 'k2'}), {'k1'})
        with self.assertRaises(StatementFingerprintUnavailableError):
            rotated.fingerprint(
                bank=SYNTHETIC_BANK,
                account_id=1,
                source_ref='doc-1',
                key_version='k1',
            )


@override_settings(
    STATEMENT_FINGERPRINT_KEYS=KEYS,
    STATEMENT_FINGERPRINT_ACTIVE_KEY='k2',
)
class StatementIdentityImportTest(TestCase):
    """Import trusts a fingerprint plus the observation, never a weak ref."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.identity = StatementIdentityService(
            keys=KEYS,
            active_key_version='k2',
            format_version=1,
        )
        self.import_service = (
            ApplicationContainer().users.bank_statement_import_service()
        )

    def _upload(self, name: str, file_hash: str = '') -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            file_hash=file_hash,
            pdf_file=SimpleUploadedFile(
                name,
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
        )

    def _import(
        self,
        upload: BankStatementUpload,
        transactions: list[dict[str, object]],
        *,
        format_version: int = 1,
        strength: str = 'strong',
        bank: str = SYNTHETIC_BANK,
        period_start: date | None = None,
        period_end: date | None = None,
        requires_markup: bool = False,
    ) -> object:
        for entry in transactions:
            entry.setdefault('source_ref_strength', strength)
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=transactions,
                bank=bank,
                format_version=format_version,
                period_start=period_start,
                period_end=period_end,
                requires_markup=requires_markup,
            )
            return self.import_service.import_statement(upload)

    def _canonical_row(
        self,
        upload: BankStatementUpload,
        *,
        source_ref: str,
        amount: Decimal = Decimal('100.00'),
        key_version: str = 'k2',
    ) -> BankStatementRow:
        fingerprint = self.identity.fingerprint(
            bank=SYNTHETIC_BANK,
            account_id=self.account.pk,
            source_ref=source_ref,
            key_version=key_version,
        )
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=amount,
            date=WHEN,
            source_ref=source_ref,
            source_fingerprint=fingerprint.digest,
            source_fingerprint_key_version=fingerprint.key_version,
            source_fingerprint_format_version=fingerprint.format_version,
        )
        return BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=amount,
            description='Продукты',
            source_ref=source_ref,
            source_fingerprint=fingerprint.digest,
            source_fingerprint_key_version=fingerprint.key_version,
            source_fingerprint_format_version=fingerprint.format_version,
            source_format_version=1,
            transaction=movement,
            decision=BankStatementRow.Decision.NEW,
        )

    def test_exact_repeat_creates_a_row_linked_to_the_canonical_row(
        self,
    ) -> None:
        canonical_upload = self._upload('canonical.pdf')
        canonical = self._canonical_row(
            canonical_upload,
            source_ref='doc-1',
        )
        upload = self._upload('repeat.pdf')

        self._import(
            upload,
            [
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Продукты',
                    'source_ref': 'doc-1',
                    'row_position': 0,
                },
            ],
        )

        duplicate = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            duplicate.decision,
            BankStatementRow.Decision.DUPLICATE,
        )
        self.assertEqual(duplicate.canonical_row, canonical)
        self.assertIsNone(duplicate.transaction)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_repeated_source_ref_does_not_cancel_a_real_operation(self) -> None:
        upload = self._upload('reused.pdf', file_hash='reused-file')

        self._import(
            upload,
            [
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Кофе',
                    'source_ref': 'reused-ref',
                    'row_position': 0,
                },
                {
                    'date': WHEN,
                    'amount': Decimal('-50.00'),
                    'description': 'Кофе',
                    'source_ref': 'reused-ref',
                    'row_position': 1,
                },
            ],
        )

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            2,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('850.00'))

    def test_legacy_raw_reference_is_matched_and_backfilled_once(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        legacy = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=WHEN,
            source_ref='legacy-ref',
        )
        upload = self._upload('legacy.pdf')

        self._import(
            upload,
            [
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Продукты',
                    'source_ref': 'legacy-ref',
                    'row_position': 0,
                },
            ],
        )

        legacy.refresh_from_db()
        self.assertTrue(legacy.source_fingerprint)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(row.transaction_id, legacy.pk)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_cross_file_weak_reference_stays_unresolved(self) -> None:
        first = self._upload('first.pdf', file_hash='first-file')
        self._import(
            first,
            [
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Кофе',
                    'source_ref': 'weak-ref',
                    'row_position': 0,
                },
            ],
            strength='weak',
        )
        second = self._upload('second.pdf', file_hash='second-file')

        self._import(
            second,
            [
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Кофе',
                    'source_ref': 'weak-ref',
                    'row_position': 0,
                },
            ],
            strength='weak',
        )

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        row = BankStatementRow.objects.get(upload=second)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNotNone(row.candidate)

    def test_cross_file_weak_reference_keeps_unresolved_observation(
        self,
    ) -> None:
        period_start = date(2026, 3, 1)
        period_end = date(2026, 3, 31)
        first = self._upload('sber-first.pdf', file_hash='sber-first-file')
        first_entries: list[dict[str, object]] = [
            {
                'date': WHEN,
                'amount': Decimal('-500.00'),
                'description': 'Перевод',
                'source_ref': '654321',
                'category_name': None,
                'row_position': 0,
            },
        ]
        self._import(
            first,
            first_entries,
            bank='sberbank',
            strength='weak',
            period_start=period_start,
            period_end=period_end,
        )
        unresolved = BankStatementRow.objects.get(upload=first)
        self.assertEqual(
            unresolved.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(unresolved.transaction)

        second = self._upload('sber-second.pdf', file_hash='sber-second-file')
        second_entries: list[dict[str, object]] = [
            {
                'date': WHEN,
                'amount': Decimal('-500.00'),
                'description': 'Перевод',
                'source_ref': '654321',
                'category_name': None,
                'row_position': 0,
            },
            {
                'date': WHEN,
                'amount': Decimal('-10.00'),
                'description': 'Контрольная операция',
                'source_ref': '999999',
                'category_name': None,
                'row_position': 1,
            },
        ]
        self._import(
            second,
            second_entries,
            bank='sberbank',
            strength='weak',
            period_start=period_start,
            period_end=period_end,
        )

        second.refresh_from_db()
        self.assertEqual(
            second.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )
        rows = list(second.statement_rows.order_by('source_row_position'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [row.source_ref for row in rows],
            ['654321', '999999'],
        )
        for row in rows:
            self.assertEqual(
                row.decision,
                BankStatementRow.Decision.AWAITING_MARKUP,
            )
            self.assertIsNone(row.transaction)
            self.assertIsNone(row.candidate)
        self.assertEqual(
            rows[0].source_fingerprint,
            unresolved.source_fingerprint,
        )
        unresolved.refresh_from_db()
        self.assertEqual(
            unresolved.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(unresolved.transaction)
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload__account=self.account,
            ).count(),
            3,
        )
        self.assertEqual(second.skipped_count, 0)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            0,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

        self._import(
            second,
            second_entries,
            bank='sberbank',
            strength='weak',
            period_start=period_start,
            period_end=period_end,
        )
        second.refresh_from_db()
        self.assertEqual(second.statement_rows.count(), 2)
        self.assertEqual(second.skipped_count, 0)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            0,
        )

    def test_cross_file_strong_reference_keeps_unresolved_observation(
        self,
    ) -> None:
        period_start = date(2026, 3, 1)
        period_end = date(2026, 3, 31)
        first = self._upload('strong-first.pdf', file_hash='strong-first-file')
        self._import(
            first,
            [
                {
                    'date': WHEN,
                    'amount': Decimal('-500.00'),
                    'description': 'Перевод',
                    'source_ref': 'strong-654321',
                    'category_name': None,
                    'row_position': 0,
                },
            ],
            bank='sberbank',
            strength='strong',
            period_start=period_start,
            period_end=period_end,
        )
        unresolved = BankStatementRow.objects.get(upload=first)
        self.assertEqual(
            unresolved.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(unresolved.transaction)

        second = self._upload(
            'strong-second.pdf',
            file_hash='strong-second-file',
        )
        second_entries: list[dict[str, object]] = [
            {
                'date': WHEN,
                'amount': Decimal('-500.00'),
                'description': 'Перевод',
                'source_ref': 'strong-654321',
                'category_name': None,
                'row_position': 0,
            },
            {
                'date': WHEN,
                'amount': Decimal('-10.00'),
                'description': 'Контрольная операция',
                'source_ref': 'strong-999999',
                'category_name': None,
                'row_position': 1,
            },
        ]
        self._import(
            second,
            second_entries,
            bank='sberbank',
            strength='strong',
            period_start=period_start,
            period_end=period_end,
        )

        second.refresh_from_db()
        self.assertEqual(
            second.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )
        rows = list(second.statement_rows.order_by('source_row_position'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [row.source_ref for row in rows],
            ['strong-654321', 'strong-999999'],
        )
        for row in rows:
            self.assertEqual(
                row.decision,
                BankStatementRow.Decision.AWAITING_MARKUP,
            )
            self.assertIsNone(row.transaction)
            self.assertIsNone(row.canonical_row)
        self.assertEqual(
            rows[0].source_fingerprint,
            unresolved.source_fingerprint,
        )
        self.assertEqual(second.skipped_count, 0)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            0,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

        self._import(
            second,
            second_entries,
            bank='sberbank',
            strength='strong',
            period_start=period_start,
            period_end=period_end,
        )
        second.refresh_from_db()
        self.assertEqual(second.statement_rows.count(), 2)
        self.assertEqual(second.skipped_count, 0)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            0,
        )

    def test_strong_observation_is_posted_once_from_markup(self) -> None:
        period_start = date(2026, 3, 1)
        period_end = date(2026, 3, 31)
        uploads = [
            self._upload(
                f'strong-post-{index}.pdf',
                file_hash=f'strong-post-{index}-file',
            )
            for index in range(2)
        ]
        for upload in uploads:
            self._import(
                upload,
                [
                    {
                        'date': WHEN,
                        'amount': Decimal('-500.00'),
                        'description': 'Перевод',
                        'source_ref': 'strong-post-ref',
                        'category_name': None,
                        'row_position': 0,
                    },
                ],
                bank='sberbank',
                strength='strong',
                period_start=period_start,
                period_end=period_end,
            )
        rows = list(
            BankStatementRow.objects.filter(
                upload__in=uploads,
            ).order_by('pk'),
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row.source_ref_strength for row in rows},
            {'strong'},
        )
        self.assertTrue(
            all(
                row.decision == BankStatementRow.Decision.AWAITING_MARKUP
                for row in rows
            ),
        )
        category = Category.objects.create(
            user=self.user,
            name='Переводы',
            type=TransactionType.EXPENSE,
        )
        markup = ApplicationContainer().users.statement_markup_service()

        markup.post(rows[0].pk, self.user.pk, category.pk)

        with self.assertRaises(StatementMarkupConflictError):
            markup.post(rows[1].pk, self.user.pk, category.pk)

        rows[0].refresh_from_db()
        rows[1].refresh_from_db()
        self.assertEqual(rows[0].decision, BankStatementRow.Decision.NEW)
        self.assertEqual(
            rows[1].decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        movement = rows[0].transaction
        if movement is None:
            self.fail('posted row has no movement')
        self.assertEqual(movement.source_ref, 'strong-post-ref')
        self.assertTrue(movement.source_fingerprint)
        self.assertEqual(movement.source_file_hash, 'strong-post-0-file')
        self.assertEqual(movement.source_row_position, 0)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('500.00'))

    def test_weak_repeated_reference_is_posted_independently(self) -> None:
        period_start = date(2026, 3, 1)
        period_end = date(2026, 3, 31)
        uploads = [
            self._upload(
                f'weak-post-{index}.pdf',
                file_hash=f'weak-post-{index}-file',
            )
            for index in range(2)
        ]
        for upload in uploads:
            self._import(
                upload,
                [
                    {
                        'date': WHEN,
                        'amount': Decimal('-500.00'),
                        'description': 'Перевод',
                        'source_ref': 'weak-post-ref',
                        'category_name': None,
                        'row_position': 0,
                    },
                ],
                bank='sberbank',
                strength='weak',
                period_start=period_start,
                period_end=period_end,
            )
        rows = list(
            BankStatementRow.objects.filter(
                upload__in=uploads,
            ).order_by('pk'),
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row.source_ref_strength for row in rows},
            {'weak'},
        )
        category = Category.objects.create(
            user=self.user,
            name='Переводы',
            type=TransactionType.EXPENSE,
        )
        markup = ApplicationContainer().users.statement_markup_service()

        for row in rows:
            markup.post(row.pk, self.user.pk, category.pk)

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            2,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('0.00'))

    def test_ambiguous_strong_reference_stays_weak_through_replay(self) -> None:
        period_start = date(2026, 3, 1)
        period_end = date(2026, 3, 31)
        entries: list[dict[str, object]] = [
            {
                'date': WHEN,
                'amount': Decimal('-500.00'),
                'description': 'Перевод',
                'source_ref': 'ambiguous-strong-ref',
                'category_name': None,
                'row_position': position,
            }
            for position in range(2)
        ]
        first = self._upload(
            'ambiguous-strong-first.pdf',
            file_hash='ambiguous-strong-first-file',
        )
        self._import(
            first,
            entries,
            bank='sberbank',
            strength='strong',
            period_start=period_start,
            period_end=period_end,
        )
        first_rows = list(first.statement_rows.order_by('source_row_position'))
        self.assertEqual(len(first_rows), 2)
        self.assertEqual(
            {row.source_ref_strength for row in first_rows},
            {'weak'},
        )

        second = self._upload(
            'ambiguous-strong-second.pdf',
            file_hash='ambiguous-strong-second-file',
        )
        self._import(
            second,
            entries,
            bank='sberbank',
            strength='strong',
            period_start=period_start,
            period_end=period_end,
        )
        second.refresh_from_db()
        self.assertEqual(
            second.processing_mode,
            BankStatementUpload.ProcessingMode.RECONCILIATION,
        )
        rows = list(second.statement_rows.order_by('source_row_position'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row.source_ref_strength for row in rows},
            {'weak'},
        )

        self._import(
            second,
            entries,
            bank='sberbank',
            strength='strong',
            period_start=period_start,
            period_end=period_end,
        )
        second.refresh_from_db()
        rows = list(second.statement_rows.order_by('source_row_position'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row.source_ref_strength for row in rows},
            {'weak'},
        )
        self.assertEqual(second.skipped_count, 0)

        category = Category.objects.create(
            user=self.user,
            name='Переводы',
            type=TransactionType.EXPENSE,
        )
        markup = ApplicationContainer().users.statement_markup_service()
        for row in rows:
            markup.post(row.pk, self.user.pk, category.pk)

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            2,
        )
        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=second,
                transaction__isnull=False,
            ).count(),
            2,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('0.00'))

    def test_ambiguous_reference_is_not_an_exact_duplicate(self) -> None:
        canonical_upload = self._upload('ambiguous-canonical.pdf')
        canonical = self._canonical_row(
            canonical_upload,
            source_ref='ambiguous-ref',
        )
        upload = self._upload('ambiguous-repeat.pdf')

        self._import(
            upload,
            [
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Продукты',
                    'source_ref': 'ambiguous-ref',
                    'category_name': None,
                    'row_position': 0,
                },
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Продукты',
                    'source_ref': 'ambiguous-ref',
                    'category_name': None,
                    'row_position': 1,
                },
            ],
            requires_markup=True,
        )

        rows = list(upload.statement_rows.order_by('source_row_position'))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(
                row.decision,
                BankStatementRow.Decision.AWAITING_MARKUP,
            )
            self.assertIsNone(row.canonical_row)
            self.assertIsNone(row.transaction)
        self.assertEqual(canonical.source_ref, 'ambiguous-ref')
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )

    def test_legacy_resolved_row_becomes_the_canonical_row(self) -> None:
        canonical_upload = self._upload('legacy-row.pdf')
        canonical = BankStatementRow.objects.create(
            upload=canonical_upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            source_ref='legacy-row-ref',
            decision=BankStatementRow.Decision.NOT_A_PAYMENT,
        )
        upload = self._upload('legacy-row-repeat.pdf')

        self._import(
            upload,
            [
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Продукты',
                    'source_ref': 'legacy-row-ref',
                    'row_position': 0,
                },
            ],
        )

        canonical.refresh_from_db()
        self.assertTrue(canonical.source_fingerprint)
        duplicate = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            duplicate.decision,
            BankStatementRow.Decision.DUPLICATE,
        )
        self.assertEqual(duplicate.canonical_row_id, canonical.pk)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            0,
        )

    def test_row_position_drift_requires_manual_reassignment(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=WHEN,
            source_file_hash='same-file',
            source_row_position=0,
            source_format_version=1,
        )
        upload = self._upload('drift.pdf', file_hash='same-file')

        self._import(
            upload,
            [
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Продукты',
                    'row_position': 0,
                },
            ],
            format_version=2,
        )

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )

    @override_settings(
        STATEMENT_FINGERPRINT_KEYS=KEYS,
        STATEMENT_FINGERPRINT_ACTIVE_KEY='k2',
        STATEMENT_FINGERPRINT_FORMAT_VERSION=2,
    )
    def test_incompatible_fingerprint_format_blocks_auto_posting(
        self,
    ) -> None:
        old = StatementIdentityService(
            keys=KEYS,
            active_key_version='k2',
            format_version=1,
        ).fingerprint(
            bank=SYNTHETIC_BANK,
            account_id=self.account.pk,
            source_ref='doc-1',
        )
        canonical_upload = self._upload('format-v1.pdf')
        BankStatementRow.objects.create(
            upload=canonical_upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            source_ref='doc-1',
            source_fingerprint=old.digest,
            source_fingerprint_key_version=old.key_version,
            source_fingerprint_format_version=old.format_version,
            decision=BankStatementRow.Decision.NEW,
        )
        upload = self._upload('format-v2.pdf')
        service = ApplicationContainer().users.bank_statement_import_service()

        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=[
                    {
                        'date': WHEN,
                        'amount': Decimal('-100.00'),
                        'description': 'Продукты',
                        'source_ref': 'doc-1',
                        'row_position': 0,
                    },
                ],
                bank=SYNTHETIC_BANK,
            )
            result = service.import_statement(upload)

        self.assertEqual(result.expense_count, 0)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            0,
        )
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    @override_settings(STATEMENT_FINGERPRINT_KEYS={})
    def test_missing_fingerprint_configuration_blocks_auto_posting(
        self,
    ) -> None:
        service = ApplicationContainer().users.bank_statement_import_service()
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=[
                    {
                        'date': WHEN,
                        'amount': Decimal('-100.00'),
                        'description': 'Продукты',
                        'source_ref': 'doc-1',
                        'row_position': 0,
                    },
                ],
                bank=SYNTHETIC_BANK,
            )
            upload = self._upload('unconfigured.pdf')
            result = service.import_statement(upload)

        self.assertEqual(result.income_count, 0)
        self.assertEqual(result.expense_count, 0)
        self.assertEqual(Transaction.objects.count(), 0)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )

    @override_settings(
        STATEMENT_FINGERPRINT_KEYS={'k2': 'second-test-secret'},
        STATEMENT_FINGERPRINT_ACTIVE_KEY='k2',
    )
    def test_lost_key_forbids_negative_inference_and_auto_posting(
        self,
    ) -> None:
        canonical_upload = self._upload('old-key.pdf')
        self._canonical_row(
            canonical_upload,
            source_ref='doc-1',
            key_version='k1',
        )
        upload = self._upload('lost-key.pdf')
        service = ApplicationContainer().users.bank_statement_import_service()

        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=[
                    {
                        'date': WHEN,
                        'amount': Decimal('-100.00'),
                        'description': 'Продукты',
                        'source_ref': 'doc-1',
                        'row_position': 0,
                    },
                ],
                bank=SYNTHETIC_BANK,
            )
            result = service.import_statement(upload)

        self.assertEqual(result.expense_count, 0)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )


@override_settings(
    STATEMENT_FINGERPRINT_KEYS=KEYS,
    STATEMENT_FINGERPRINT_ACTIVE_KEY='k2',
)
class StaleRunAfterRetentionTest(TestCase):
    """A run that resumes after retention must not write bank data again."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.service = (
            ApplicationContainer().users.bank_statement_import_service()
        )

    def _upload(self) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            file_hash='paused-file',
            pdf_file=SimpleUploadedFile(
                'paused.pdf',
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
            status=BankStatementUpload.Status.PROCESSING,
            celery_task_id='run-a',
            expires_at=timezone.now() + timedelta(minutes=5),
        )

    def _transactions(self) -> list[dict[str, object]]:
        return [
            {
                'date': WHEN,
                'amount': Decimal('-100.00'),
                'description': 'Продукты',
                'source_ref': 'row-1',
                'row_position': 0,
            },
            {
                'date': WHEN,
                'amount': Decimal('-200.00'),
                'description': 'Продукты',
                'source_ref': 'row-2',
                'row_position': 1,
            },
        ]

    def _import_with_pause(
        self,
        upload: BankStatementUpload,
        pause: Callable[[], None],
    ) -> object:
        """Import two rows and act once the first row is already posted."""
        calls = 0

        def classify(
            _service: object,
            _description: str,
            _type_value: str,
            _existing_categories: list[str],
        ) -> str:
            nonlocal calls
            calls += 1
            if calls == PAUSE_BEFORE_SECOND_ROW:
                pause()
            return FALLBACK_CATEGORY

        with (
            patch(
                'hasta_la_vista_money.users.services.bank_statement_import.'
                'BankStatementParser',
            ) as parser,
            patch.object(
                BankStatementImportService,
                '_classify_category',
                new=classify,
            ),
        ):
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=self._transactions(),
                bank=SYNTHETIC_BANK,
            )
            return self.service.import_statement(upload)

    def _assert_only_first_row_posted(self) -> None:
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_cleanup_stops_the_remaining_rows_of_a_resumed_run(self) -> None:
        upload = self._upload()

        def cleanup() -> None:
            container = ApplicationContainer()
            container.users.bank_statement_retention_service().cleanup_expired(
                now=upload.expires_at + timedelta(minutes=1),
            )

        self._import_with_pause(upload, cleanup)

        self._assert_only_first_row_posted()
        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        self.assertIsNone(upload.statement_closing_balance)

    def test_new_active_run_stops_the_previous_run(self) -> None:
        upload = self._upload()

        def start_new_run() -> None:
            BankStatementUpload.objects.filter(pk=upload.pk).update(
                celery_task_id='run-b',
            )

        self._import_with_pause(upload, start_new_run)

        self._assert_only_first_row_posted()

    def test_passed_deadline_stops_the_run_without_cleanup(self) -> None:
        upload = self._upload()

        def expire() -> None:
            BankStatementUpload.objects.filter(pk=upload.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1),
            )

        self._import_with_pause(upload, expire)

        self._assert_only_first_row_posted()

    def _ambiguous_rows(self, upload: BankStatementUpload) -> list[int]:
        rows = [
            BankStatementRow.objects.create(
                upload=upload,
                source_row_position=position,
                transaction_type=BankStatementRow.TransactionType.EXPENSE,
                transaction_date=WHEN,
                amount=Decimal('100.00'),
                description='Перевод',
                source_ref='ambiguous-owner-ref',
                source_ref_strength='strong',
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            )
            for position in range(2)
        ]
        return [row.pk for row in rows]

    def _ambiguous_transactions(self) -> list[dict[str, object]]:
        return [
            {
                'date': WHEN,
                'amount': Decimal('-100.00'),
                'description': 'Перевод',
                'source_ref': 'ambiguous-owner-ref',
                'source_ref_strength': 'strong',
                'category_name': None,
                'row_position': position,
            }
            for position in range(2)
        ]

    def test_stale_run_does_not_weaken_rows_of_the_new_owner(self) -> None:
        upload = self._upload()
        row_ids = self._ambiguous_rows(upload)
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            celery_task_id='run-b',
        )

        result = self.service._process_transactions(
            upload,
            self._ambiguous_transactions(),
            [],
            StatementParseResult(
                transactions=self._ambiguous_transactions(),
                bank='sberbank',
            ),
            run_id='run-a',
        )

        self.assertTrue(result[4])
        self.assertEqual(
            set(
                BankStatementRow.objects.filter(
                    pk__in=row_ids,
                ).values_list('source_ref_strength', flat=True),
            ),
            {'strong'},
        )
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            0,
        )

    def test_resumed_run_weakens_already_processed_ambiguous_rows(self) -> None:
        upload = self._upload()
        row_ids = self._ambiguous_rows(upload)
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            processed_transactions=2,
        )

        result = self.service._process_transactions(
            upload,
            self._ambiguous_transactions(),
            [],
            StatementParseResult(
                transactions=self._ambiguous_transactions(),
                bank='sberbank',
            ),
            run_id='run-a',
        )

        self.assertFalse(result[4])
        self.assertEqual(
            set(
                BankStatementRow.objects.filter(
                    pk__in=row_ids,
                ).values_list('source_ref_strength', flat=True),
            ),
            {'weak'},
        )
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            0,
        )


class FinalizationAfterRetentionTest(TestCase):
    """The worker's last write must not restore cleaned bank balances."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def test_finalization_does_not_restore_balance_of_a_cleaned_upload(
        self,
    ) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            file_hash='paused-file',
            pdf_file=SimpleUploadedFile(
                'paused.pdf',
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        original_import = BankStatementImportService.import_statement

        def import_then_clean(
            service: BankStatementImportService,
            target: BankStatementUpload,
        ) -> StatementImportResult:
            result = original_import(service, target)
            ApplicationContainer().users.bank_statement_retention_service().cleanup_expired(
                now=upload.expires_at + timedelta(minutes=1),
            )
            return result

        with (
            patch(
                'hasta_la_vista_money.users.services.bank_statement_import.'
                'BankStatementParser',
            ) as parser,
            patch.object(
                BankStatementImportService,
                'import_statement',
                new=import_then_clean,
            ),
        ):
            parser.return_value.parse.return_value = StatementParseResult(
                transactions=[
                    {
                        'date': WHEN,
                        'amount': Decimal('-100.00'),
                        'description': 'Продукты',
                        'source_ref': 'row-1',
                        'row_position': 0,
                    },
                ],
                bank=SYNTHETIC_BANK,
                closing_balance=Decimal('900.00'),
            )
            process_bank_statement_task.apply(args=[upload.pk]).get()

        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        self.assertIsNone(upload.statement_closing_balance)
        self.assertIsNone(upload.account_balance_after)
        self.assertEqual(
            upload.balance_reason,
            BankStatementUpload.BalanceReason.BANK_DATA_CLEANED,
        )


class CanonicalDuplicateLinkTest(TestCase):
    """A duplicate may only point at a resolved, non-duplicate canonical row."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('0.00'),
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
        )
        self.link_service = (
            ApplicationContainer().users.statement_row_link_service()
        )

    def _row(self) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            decision=BankStatementRow.Decision.PENDING,
        )

    def test_duplicate_chain_is_not_closed_automatically(self) -> None:
        first = self._row()
        second = self._row()
        second.decision = BankStatementRow.Decision.NOT_A_PAYMENT
        second.save(update_fields=['decision'])
        self.link_service.link_duplicate(first.pk, second.pk, self.user.pk)

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.link_service.link_duplicate(
                second.pk,
                first.pk,
                self.user.pk,
            )

    def test_linking_a_row_to_itself_is_refused(self) -> None:
        row = self._row()
        with self.assertRaises(ReconciliationDecisionConflictError):
            self.link_service.link_duplicate(row.pk, row.pk, self.user.pk)


class CanonicalDuplicateValidationTest(TestCase):
    """Only a resolved, proven row of the same account is a canonical row."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('0.00'),
        )
        self.other_account = Account.objects.create(
            user=self.user,
            name_account='Другой',
            balance=Decimal('0.00'),
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
        )
        self.other_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.other_account,
            pdf_file='other.pdf',
        )
        self.service = ApplicationContainer().users.statement_row_link_service()

    def _row(
        self,
        *,
        upload: BankStatementUpload | None = None,
        amount: Decimal = Decimal('100.00'),
        position: int = 0,
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=upload or self.upload,
            source_row_position=position,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=amount,
            decision=BankStatementRow.Decision.PENDING,
        )

    def test_unresolved_canonical_row_is_refused(self) -> None:
        row = self._row()
        canonical = self._row(position=1)
        canonical.decision = BankStatementRow.Decision.AWAITING_MARKUP
        canonical.save(update_fields=['decision'])

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.service.link_duplicate(row.pk, canonical.pk, self.user.pk)

    def test_legacy_skip_without_approved_code_is_refused(self) -> None:
        row = self._row()
        canonical = self._row(position=1)
        canonical.decision = BankStatementRow.Decision.SKIPPED
        canonical.save(update_fields=['decision'])

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.service.link_duplicate(row.pk, canonical.pk, self.user.pk)

    def test_canonical_row_of_another_account_is_refused(self) -> None:
        row = self._row()
        canonical = self._row(upload=self.other_upload, position=1)

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.service.link_duplicate(row.pk, canonical.pk, self.user.pk)

    def test_canonical_row_with_other_amount_is_refused(self) -> None:
        row = self._row()
        canonical = self._row(amount=Decimal('50.00'), position=1)
        canonical.decision = BankStatementRow.Decision.NOT_A_PAYMENT
        canonical.save(update_fields=['decision'])

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.service.link_duplicate(row.pk, canonical.pk, self.user.pk)

    def test_approved_skip_of_the_same_observation_is_allowed(self) -> None:
        row = self._row()
        canonical = self._row(position=1)
        canonical.decision = BankStatementRow.Decision.SKIPPED
        canonical.exclusion_code = (
            BankStatementRow.ExclusionCode.NON_FINANCIAL_BANK_RECORD
        )
        canonical.save(update_fields=['decision', 'exclusion_code'])

        linked = self.service.link_duplicate(
            row.pk,
            canonical.pk,
            self.user.pk,
        )

        self.assertEqual(
            linked.decision,
            BankStatementRow.Decision.DUPLICATE,
        )
        self.assertEqual(linked.canonical_row, canonical)


class MovementSharingTest(TestCase):
    """Different statement rows never share one movement."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        self.movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=WHEN,
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
        )
        self.service = BankStatementReconciliationService()

    def _pending_row(self, position: int) -> BankStatementRow:
        row = BankStatementRow.objects.create(
            upload=self.upload,
            source_row_position=position,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            decision=BankStatementRow.Decision.PENDING,
        )
        BankStatementCandidate.objects.create(
            row=row,
            transaction=self.movement,
            description='Кандидат',
        )
        return row

    def test_second_row_cannot_link_the_same_movement(self) -> None:
        first = self._pending_row(0)
        second = self._pending_row(1)
        first_candidate = first.candidates.get()
        second_candidate = second.candidates.get()

        self.service.decide(
            first.pk,
            BankStatementRow.Decision.LINKED,
            self.user.pk,
            first_candidate.pk,
        )
        with self.assertRaises(
            (ReconciliationDecisionConflictError, StaleStatementCandidateError),
        ):
            self.service.decide(
                second.pk,
                BankStatementRow.Decision.LINKED,
                self.user.pk,
                second_candidate.pk,
            )

    def test_duplicate_observation_does_not_take_the_transfer_side(
        self,
    ) -> None:
        target = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            balance=Decimal('0.00'),
        )
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=target,
            amount=Decimal('100.00'),
            exchange_date=WHEN,
        )
        canonical = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            transfer=transfer,
            decision=BankStatementRow.Decision.TRANSFERRED,
        )

        duplicate = BankStatementRow.objects.create(
            upload=self.upload,
            source_row_position=99,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            canonical_row=canonical,
            decision=BankStatementRow.Decision.DUPLICATE,
        )

        self.assertIsNone(duplicate.transfer)
        self.assertEqual(duplicate.canonical_row, canonical)


class RetentionKeepsFingerprintTest(TestCase):
    """Cleanup removes bank data but keeps the technical fingerprint."""

    def test_cleanup_keeps_fingerprint_and_drops_raw_reference(self) -> None:
        user = cast('User', UserFactory())
        account = Account.objects.create(
            user=user,
            name_account='Основной',
            balance=Decimal('0.00'),
        )
        fingerprint = StatementIdentityService(
            keys=KEYS,
            active_key_version='k2',
            format_version=1,
        ).fingerprint(
            bank=SYNTHETIC_BANK,
            account_id=account.pk,
            source_ref='doc-1',
        )
        upload = BankStatementUpload.objects.create(
            user=user,
            account=account,
            pdf_file='statement.pdf',
            expires_at=timezone.now(),
        )
        BankStatementRow.objects.create(
            upload=upload,
            source_ref='doc-1',
            source_fingerprint=fingerprint.digest,
            source_fingerprint_key_version=fingerprint.key_version,
            source_fingerprint_format_version=fingerprint.format_version,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )

        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()

        row = BankStatementRow.objects.get(upload=upload)
        self.assertIsNone(row.source_ref)
        self.assertEqual(row.source_fingerprint, fingerprint.digest)
        self.assertEqual(row.source_fingerprint_key_version, 'k2')


class ReconciliationUsesBalanceServiceTest(TestCase):
    """A manual decision changes the balance through the shared service."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
        )
        self.row = BankStatementRow.objects.create(
            upload=self.upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            suggested_category='Продукты',
            decision=BankStatementRow.Decision.PENDING,
        )

    def test_new_decision_applies_the_delta_through_balance_service(
        self,
    ) -> None:
        with patch.object(
            BalanceService,
            'apply_account_deltas',
            autospec=True,
            side_effect=BalanceService.apply_account_deltas,
        ) as apply_deltas:
            BankStatementReconciliationService().decide(
                self.row.pk,
                BankStatementRow.Decision.NEW,
                self.user.pk,
            )

        apply_deltas.assert_called_once()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))


class ReconciliationRejectsRepeatedFingerprintTest(TestCase):
    """Posting NEW twice for one proven operation must not double money."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        self.fingerprint = StatementIdentityService(
            keys=KEYS,
            active_key_version='k2',
            format_version=1,
        ).fingerprint(
            bank=SYNTHETIC_BANK,
            account_id=self.account.pk,
            source_ref='doc-1',
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=WHEN,
            source_ref='doc-1',
            source_fingerprint=self.fingerprint.digest,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
        )
        self.row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            suggested_category='Продукты',
            source_ref='doc-1',
            source_ref_strength='strong',
            source_fingerprint=self.fingerprint.digest,
            decision=BankStatementRow.Decision.PENDING,
        )

    def test_new_decision_is_refused_for_an_existing_fingerprint(self) -> None:
        with self.assertRaises(ReconciliationDecisionConflictError):
            BankStatementReconciliationService().decide(
                self.row.pk,
                BankStatementRow.Decision.NEW,
                self.user.pk,
            )

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.PENDING,
        )


class ReconciliationAllowsWeakReferenceTest(TestCase):
    """A weak or reused reference never proves a repeat by itself."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        self.fingerprint = StatementIdentityService(
            keys=KEYS,
            active_key_version='k2',
            format_version=1,
        ).fingerprint(
            bank=SYNTHETIC_BANK,
            account_id=self.account.pk,
            source_ref='doc-1',
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=WHEN,
            source_ref='doc-1',
            source_fingerprint=self.fingerprint.digest,
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
        )

    def _row(
        self,
        *,
        amount: Decimal = Decimal('100.00'),
        strength: str = 'weak',
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=self.upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=amount,
            suggested_category='Продукты',
            source_ref='doc-1',
            source_ref_strength=strength,
            source_fingerprint=self.fingerprint.digest,
            decision=BankStatementRow.Decision.PENDING,
        )

    def test_weak_reference_posts_a_second_legitimate_operation(self) -> None:
        row = self._row()

        BankStatementReconciliationService().decide(
            row.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            2,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_strong_reference_with_other_amount_still_posts(self) -> None:
        row = self._row(amount=Decimal('150.00'), strength='strong')

        BankStatementReconciliationService().decide(
            row.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            2,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('850.00'))


class LinkedDateInvalidationTest(TestCase):
    """A date edit invalidates checks; a category edit does not."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        self.other_category = Category.objects.create(
            user=self.user,
            name='Кафе',
            type=TransactionType.EXPENSE,
        )
        self.movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=WHEN,
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
            statement_closing_balance=Decimal('900.00'),
            account_balance_after=Decimal('1000.00'),
            balance_discrepancy=Decimal('-100.00'),
        )
        BankStatementRow.objects.create(
            upload=self.upload,
            transaction=self.movement,
            decision=BankStatementRow.Decision.LINKED,
        )
        self.transaction_service = (
            ApplicationContainer().transactions.transaction_service()
        )

    def _update(
        self,
        *,
        category: Category,
        when: datetime,
    ) -> None:
        self.transaction_service.update_transaction(
            UpdateTransactionCommand(
                user=self.user,
                transaction_obj=self.movement,
                account=self.account,
                category=category,
                amount=Decimal('100.00'),
                transaction_date=when,
                type_value=TransactionType.EXPENSE,
            ),
        )

    def _verify_matched(self) -> None:
        """Store a real matched check at the movement's own moment."""
        self.upload.statement_closing_balance = Decimal('1000.00')
        self.upload.balance_currency = 'RUB'
        balance_type = BankStatementUpload.BalanceType
        self.upload.balance_type = balance_type.EXACT_MOMENT
        self.upload.balance_moment = WHEN
        self.upload.balance_bank_date = WHEN.date()
        self.upload.save(
            update_fields=[
                'statement_closing_balance',
                'balance_currency',
                'balance_type',
                'balance_moment',
                'balance_bank_date',
            ],
        )
        users = ApplicationContainer().users
        verification = users.statement_balance_verification_service()
        verification.verify(self.upload)
        self.upload.refresh_from_db()
        self.assertEqual(
            self.upload.balance_result,
            BankStatementUpload.BalanceResult.MATCHED,
        )
        self.assertTrue(self.upload.balance_is_actual)

    def test_date_change_invalidates_the_upload_check(self) -> None:
        self._update(
            category=self.category,
            when=datetime(2026, 3, 12, 12, 0, tzinfo=UTC),
        )

        self.upload.refresh_from_db()
        self.assertIsNone(self.upload.account_balance_after)
        self.assertIsNone(self.upload.balance_discrepancy)

    def test_date_change_marks_a_matched_check_stale(self) -> None:
        self._verify_matched()

        self._update(
            category=self.category,
            when=WHEN + timedelta(days=2),
        )

        self.upload.refresh_from_db()
        self.assertFalse(self.upload.balance_is_actual)
        self.assertEqual(
            self.upload.balance_reason,
            BankStatementUpload.BalanceReason.MONEY_OR_DATE_CHANGED,
        )
        self.assertIsNone(self.upload.account_balance_after)
        self.assertIsNone(self.upload.balance_discrepancy)
        users = ApplicationContainer().users
        verification = users.statement_balance_verification_service()
        state = verification.describe(
            verification.refresh_actuality(self.upload),
        )
        self.assertFalse(state.actual)
        self.assertEqual(state.label, 'Требует перепроверки')

    def test_category_change_keeps_the_upload_check(self) -> None:
        self._update(category=self.other_category, when=WHEN)

        self.upload.refresh_from_db()
        self.assertEqual(
            self.upload.account_balance_after,
            Decimal('1000.00'),
        )
        self.assertEqual(
            self.upload.balance_discrepancy,
            Decimal('-100.00'),
        )


class SharedMovementMigrationTest(TransactionTestCase):
    """The uniqueness migration keeps proven repeats and frees ambiguity."""

    migrate_from = [
        ('users', '0025_bankstatementdecisionaudit_exclusion_code_and_more'),
    ]
    migrate_to = [('users', '0032_bankstatementrow_source_ref_strength')]

    def tearDown(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_unresolved_links_are_released_in_any_order(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        old_apps = executor.migrate(self.migrate_from).apps
        user = old_apps.get_model('users', 'User').objects.create(
            username='migration-order-user',
        )
        account_model = old_apps.get_model('finance_account', 'Account')
        category_model = old_apps.get_model('transactions', 'Category')
        movement_model = old_apps.get_model('transactions', 'Transaction')
        account = account_model.objects.create(
            user=user,
            name_account='Основной',
            balance=Decimal('1000.00'),
        )
        category = category_model.objects.create(
            user=user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        upload = old_apps.get_model(
            'users',
            'BankStatementUpload',
        ).objects.create(
            user_id=user.pk,
            account_id=account.pk,
            pdf_file='statement.pdf',
        )
        row_model = old_apps.get_model('users', 'BankStatementRow')

        def movement() -> Model:
            movement_obj: Model = movement_model.objects.create(
                user=user,
                account=account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal('100.00'),
                date=WHEN,
            )
            return movement_obj

        def row(
            movement_obj: Model,
            position: int,
            decision: str,
        ) -> Any:
            return row_model.objects.create(
                upload_id=upload.pk,
                source_row_position=position,
                transaction_id=movement_obj.pk,
                transaction_type='expense',
                transaction_date=WHEN,
                amount=Decimal('100.00'),
                decision=decision,
            )

        first_movement = movement()
        first_unresolved = row(first_movement, 0, 'awaiting_markup')
        first_resolved = row(first_movement, 1, 'new')
        second_movement = movement()
        second_resolved = row(second_movement, 2, 'new')
        second_unresolved = row(second_movement, 3, 'awaiting_markup')
        third_movement = movement()
        third_first = row(third_movement, 4, 'pending')
        third_second = row(third_movement, 5, 'awaiting_markup')

        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(self.migrate_to)

        first_unresolved_row = BankStatementRow.objects.get(
            pk=first_unresolved.pk,
        )
        first_resolved_row = BankStatementRow.objects.get(
            pk=first_resolved.pk,
        )
        second_resolved_row = BankStatementRow.objects.get(
            pk=second_resolved.pk,
        )
        second_unresolved_row = BankStatementRow.objects.get(
            pk=second_unresolved.pk,
        )
        third_rows = BankStatementRow.objects.filter(
            pk__in=[third_first.pk, third_second.pk],
        )

        self.assertIsNone(first_unresolved_row.transaction_id)
        self.assertEqual(
            first_unresolved_row.decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertEqual(first_resolved_row.transaction_id, first_movement.pk)
        self.assertEqual(second_resolved_row.transaction_id, second_movement.pk)
        self.assertIsNone(second_unresolved_row.transaction_id)
        self.assertFalse(
            third_rows.filter(transaction__isnull=False).exists(),
        )
        self.assertFalse(third_rows.exclude(decision='pending').exists())
        for transaction_id in (
            first_movement.pk,
            second_movement.pk,
            third_movement.pk,
        ):
            self.assertLessEqual(
                BankStatementRow.objects.filter(
                    transaction_id=transaction_id,
                ).count(),
                1,
            )

    def test_shared_movement_becomes_repeat_or_pending(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        old_apps = executor.migrate(self.migrate_from).apps
        user = old_apps.get_model('users', 'User').objects.create(
            username='migration-user',
        )
        account_model = old_apps.get_model('finance_account', 'Account')
        category_model = old_apps.get_model('transactions', 'Category')
        movement_model = old_apps.get_model('transactions', 'Transaction')
        account = account_model.objects.create(
            user=user,
            name_account='Основной',
            balance=Decimal('1000.00'),
        )
        category = category_model.objects.create(
            user=user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        movement = movement_model.objects.create(
            user=user,
            account=account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=WHEN,
        )
        upload = old_apps.get_model(
            'users',
            'BankStatementUpload',
        ).objects.create(
            user_id=user.pk,
            account_id=account.pk,
            pdf_file='statement.pdf',
        )
        row_model = old_apps.get_model('users', 'BankStatementRow')
        canonical = row_model.objects.create(
            upload_id=upload.pk,
            source_row_position=0,
            transaction_id=movement.pk,
            transaction_type='expense',
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            decision='linked',
        )
        repeat = row_model.objects.create(
            upload_id=upload.pk,
            source_row_position=1,
            transaction_id=movement.pk,
            transaction_type='expense',
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            decision='linked',
        )
        different = row_model.objects.create(
            upload_id=upload.pk,
            source_row_position=2,
            transaction_id=movement.pk,
            transaction_type='expense',
            transaction_date=WHEN,
            amount=Decimal('50.00'),
            decision='linked',
        )
        foreign_account = account_model.objects.create(
            user=user,
            name_account='Другой',
            balance=Decimal('0.00'),
        )
        foreign_upload = old_apps.get_model(
            'users',
            'BankStatementUpload',
        ).objects.create(
            user_id=user.pk,
            account_id=foreign_account.pk,
            pdf_file='foreign.pdf',
        )
        foreign = row_model.objects.create(
            upload_id=foreign_upload.pk,
            source_row_position=0,
            transaction_id=movement.pk,
            transaction_type='expense',
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            decision='linked',
        )
        old_apps.get_model(
            'users',
            'BankStatementDecisionAudit',
        ).objects.create(
            row_id=repeat.pk,
            decision='linked',
        )

        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(self.migrate_to)

        repeat_row = BankStatementRow.objects.get(pk=repeat.pk)
        different_row = BankStatementRow.objects.get(pk=different.pk)
        foreign_row = BankStatementRow.objects.get(pk=foreign.pk)
        self.assertEqual(
            repeat_row.decision,
            BankStatementRow.Decision.DUPLICATE,
        )
        self.assertEqual(repeat_row.canonical_row_id, canonical.pk)
        self.assertIsNone(repeat_row.transaction_id)
        self.assertEqual(
            different_row.decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertIsNone(different_row.transaction_id)
        self.assertEqual(
            foreign_row.decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertIsNone(foreign_row.transaction_id)
        self.assertTrue(
            repeat_row.decision_audits.filter(decision='linked').exists(),
        )
        self.account = Account.objects.get(pk=account.pk)
        self.assertEqual(self.account.balance, Decimal('1000.00'))


class ConcurrentStatementActionsTest(TransactionTestCase):
    """Concurrent retries and decisions produce exactly one effect."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def _import_markup_pair(
        self,
        source_ref: str,
        strength: str,
    ) -> list[BankStatementRow]:
        """Import two overlapping files that keep the same unresolved row."""
        period_start = date(2026, 3, 1)
        period_end = date(2026, 3, 31)
        uploads = []
        for index in range(2):
            upload = BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                file_hash=f'markup-race-{index}-{source_ref}',
                pdf_file=SimpleUploadedFile(
                    f'markup-race-{index}.pdf',
                    b'%PDF-1.4 mock pdf',
                ),
            )
            uploads.append(upload)
            with patch(
                'hasta_la_vista_money.users.services.'
                'bank_statement_import.BankStatementParser',
            ) as parser:
                parser.return_value.parse.return_value = StatementParseResult(
                    transactions=[
                        {
                            'date': WHEN,
                            'amount': Decimal('-500.00'),
                            'description': 'Перевод',
                            'source_ref': source_ref,
                            'source_ref_strength': strength,
                            'category_name': None,
                            'row_position': 0,
                        },
                    ],
                    bank='sberbank',
                    period_start=period_start,
                    period_end=period_end,
                )
                ApplicationContainer().users.bank_statement_import_service().import_statement(
                    upload,
                )
        return list(
            BankStatementRow.objects.filter(
                upload__in=uploads,
            ).order_by('pk'),
        )

    def test_concurrent_imports_of_one_observation_create_one_movement(
        self,
    ) -> None:
        uploads = [
            BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                file_hash=f'file-{index}',
                pdf_file=SimpleUploadedFile(
                    f'statement-{index}.pdf',
                    b'%PDF-1.4 mock pdf',
                ),
            )
            for index in range(2)
        ]
        barrier = Barrier(2, timeout=5)
        errors: list[Exception | None] = [None, None]

        def run(index: int) -> None:
            service = (
                ApplicationContainer().users.bank_statement_import_service()
            )
            try:
                barrier.wait(timeout=3)
                with patch(
                    'hasta_la_vista_money.users.services.'
                    'bank_statement_import.BankStatementParser',
                ) as parser:
                    parser.return_value.parse.return_value = (
                        StatementParseResult(
                            transactions=[
                                {
                                    'date': WHEN,
                                    'amount': Decimal('-100.00'),
                                    'description': 'Продукты',
                                    'source_ref': 'shared-ref',
                                    'row_position': 0,
                                },
                            ],
                            bank=SYNTHETIC_BANK,
                        )
                    )
                    service.import_statement(uploads[index])
            except Exception as exc:
                errors[index] = exc
            finally:
                connections.close_all()

        threads = [Thread(target=run, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        for error in errors:
            if error is not None:
                self.fail(f'Concurrent import failed unexpectedly: {error}')

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_cleanup_and_replay_race_keeps_one_movement(self) -> None:
        """Cleanup and an explicit replay never resurrect deleted money."""
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=WHEN,
            description='Продукты',
        )
        self.account.balance = Decimal('900.00')
        self.account.save(update_fields=['balance'])
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file=SimpleUploadedFile(
                'race.pdf',
                b'%PDF-1.4 race statement',
                content_type='application/pdf',
            ),
            file_hash='race-file',
            status=BankStatementUpload.Status.COMPLETED,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            transaction=movement,
            decision=BankStatementRow.Decision.NEW,
        )
        barrier = Barrier(2, timeout=5)
        errors: list[Exception | None] = [None, None]

        def cleanup() -> None:
            try:
                barrier.wait(timeout=3)
                ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
            except Exception as exc:
                errors[0] = exc
            finally:
                connections.close_all()

        def replay() -> None:
            try:
                barrier.wait(timeout=3)
                ApplicationContainer().users.bank_statement_import_service().prepare_known_replay(
                    upload,
                    SimpleUploadedFile(
                        'race.pdf',
                        b'%PDF-1.4 race statement',
                        content_type='application/pdf',
                    ),
                )
            except Exception as exc:
                errors[1] = exc
            finally:
                connections.close_all()

        threads = [Thread(target=cleanup), Thread(target=replay)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        for error in errors:
            if error is not None:
                self.fail(f'Cleanup or replay failed unexpectedly: {error}')

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(row.transaction_id, movement.pk)
        upload.refresh_from_db()
        self.assertIsNone(upload.retention_cleaned_at)
        self.assertGreater(upload.expires_at, timezone.now())
        self.assertTrue(bool(upload.pdf_file))

    def test_concurrent_decisions_create_one_movement(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            suggested_category='Продукты',
            decision=BankStatementRow.Decision.PENDING,
        )
        barrier = Barrier(2, timeout=5)
        errors: list[Exception | None] = [None, None]

        def run(index: int) -> None:
            service = BankStatementReconciliationService()
            try:
                barrier.wait(timeout=3)
                service.decide(
                    row.pk,
                    BankStatementRow.Decision.NEW,
                    self.user.pk,
                )
            except Exception as exc:
                errors[index] = exc
            finally:
                connections.close_all()

        threads = [Thread(target=run, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        for error in errors:
            if error is not None:
                self.fail(f'Concurrent decision failed unexpectedly: {error}')

        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))
        self.assertEqual(
            BankStatementRow.objects.get(pk=row.pk).decision,
            BankStatementRow.Decision.NEW,
        )

    def test_concurrent_resolution_of_two_observations_keeps_one_movement(
        self,
    ) -> None:
        fingerprint = StatementIdentityService(
            keys=KEYS,
            active_key_version='k2',
            format_version=1,
        ).fingerprint(
            bank=SYNTHETIC_BANK,
            account_id=self.account.pk,
            source_ref='shared-resolution-ref',
        )
        rows = []
        for index in range(2):
            upload = BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                file_hash=f'resolution-file-{index}',
                pdf_file=f'resolution-{index}.pdf',
            )
            rows.append(
                BankStatementRow.objects.create(
                    upload=upload,
                    source_row_position=0,
                    transaction_type=TransactionType.EXPENSE,
                    transaction_date=WHEN,
                    amount=Decimal('100.00'),
                    suggested_category='Продукты',
                    source_ref='shared-resolution-ref',
                    source_ref_strength='strong',
                    source_fingerprint=fingerprint.digest,
                    source_fingerprint_key_version=fingerprint.key_version,
                    source_fingerprint_format_version=(
                        fingerprint.format_version
                    ),
                    decision=BankStatementRow.Decision.PENDING,
                ),
            )
        barrier = Barrier(2, timeout=5)
        errors: list[Exception | None] = [None, None]

        def run(index: int) -> None:
            service = BankStatementReconciliationService()
            try:
                barrier.wait(timeout=3)
                service.decide(
                    rows[index].pk,
                    BankStatementRow.Decision.NEW,
                    self.user.pk,
                )
            except Exception as exc:
                errors[index] = exc
            finally:
                connections.close_all()

        threads = [Thread(target=run, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        conflicts = [
            error
            for error in errors
            if isinstance(error, ReconciliationDecisionConflictError)
        ]
        unexpected = [
            error
            for error in errors
            if error is not None
            and not isinstance(error, ReconciliationDecisionConflictError)
        ]
        self.assertEqual(unexpected, [])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))
        decisions = sorted(
            BankStatementRow.objects.filter(
                pk__in=[row.pk for row in rows],
            ).values_list('decision', flat=True),
        )
        self.assertEqual(
            decisions,
            [
                BankStatementRow.Decision.NEW,
                BankStatementRow.Decision.PENDING,
            ],
        )

    def test_concurrent_markup_of_strong_observations_creates_one_movement(
        self,
    ) -> None:
        rows = self._import_markup_pair(
            source_ref='strong-markup-race',
            strength='strong',
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            all(
                row.decision == BankStatementRow.Decision.AWAITING_MARKUP
                for row in rows
            ),
        )
        category = Category.objects.create(
            user=self.user,
            name='Переводы',
            type=TransactionType.EXPENSE,
        )
        barrier = Barrier(2, timeout=5)
        errors: list[Exception | None] = [None, None]

        def run(index: int) -> None:
            service = ApplicationContainer().users.statement_markup_service()
            try:
                barrier.wait(timeout=3)
                service.post(rows[index].pk, self.user.pk, category.pk)
            except Exception as exc:
                errors[index] = exc
            finally:
                connections.close_all()

        threads = [Thread(target=run, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        conflicts = [
            error
            for error in errors
            if isinstance(error, StatementMarkupConflictError)
        ]
        unexpected = [
            error
            for error in errors
            if error is not None
            and not isinstance(error, StatementMarkupConflictError)
        ]
        self.assertEqual(unexpected, [])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('500.00'))
        decisions = sorted(
            BankStatementRow.objects.filter(
                pk__in=[row.pk for row in rows],
            ).values_list('decision', flat=True),
        )
        self.assertEqual(
            decisions,
            [
                BankStatementRow.Decision.AWAITING_MARKUP,
                BankStatementRow.Decision.NEW,
            ],
        )

    def _candidate_fixture(
        self,
    ) -> tuple[Transaction, BankStatementRow, BankStatementCandidate]:
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=WHEN,
            description='Продукты',
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='candidate-race.pdf',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            suggested_category='Продукты',
            decision=BankStatementRow.Decision.PENDING,
        )
        candidate = BankStatementCandidate.objects.create(
            row=row,
            transaction=movement,
            description='Продукты',
        )
        return movement, row, candidate

    def _candidate_transfer_fixture(
        self,
    ) -> tuple[TransferMoneyLog, BankStatementRow, BankStatementCandidate]:
        target = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        transfer_service = (
            ApplicationContainer().finance_account.transfer_service()
        )
        transfer = transfer_service.transfer_money(
            from_account=self.account,
            to_account=target,
            amount=Decimal('100.00'),
            user=self.user,
            exchange_date=WHEN,
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='candidate-transfer-race.pdf',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            decision=BankStatementRow.Decision.PENDING,
        )
        candidate = BankStatementCandidate.objects.create(
            row=row,
            transfer=transfer,
            description='Перевод',
        )
        return transfer, row, candidate

    def _repayment_link_fixture(
        self,
    ) -> tuple[TransferMoneyLog, BankStatementRow]:
        card = Account.objects.create(
            user=self.user,
            name_account='Кредитная карта',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        transfer = (
            ApplicationContainer()
            .finance_account.transfer_service()
            .transfer_money(
                from_account=self.account,
                to_account=card,
                amount=Decimal('100.00'),
                user=self.user,
                exchange_date=WHEN,
            )
        )
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=card,
            pdf_file='repayment-link-race.pdf',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=BankStatementRow.TransactionType.INCOME,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        BankStatementRow.objects.create(
            upload=upload,
            source_row_position=1,
            transaction_type=BankStatementRow.TransactionType.INCOME,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            transfer=transfer,
            decision=BankStatementRow.Decision.TRANSFERRED,
        )
        return transfer, row

    def _run_service_race(
        self,
        hold: Callable[[Event, Event], None],
        decide: Callable[[], object],
    ) -> list[Exception | None]:
        """Run a holder and a decision through their services in order.

        The holder announces that it locked the movement, then waits until
        the decision is about to take the movement lock before it commits
        its change. The decision then blocks on that lock, so it always
        re-reads the committed movement. The signal comes from the SQL that
        takes the lock itself, not from a service method, so it cannot fire
        before the candidate is read. No timing is guessed: the two service
        paths meet on events.
        """
        holder_locked = Event()
        decision_started = Event()
        errors: list[Exception | None] = [None, None]

        def hold_thread() -> None:
            try:
                hold(holder_locked, decision_started)
            except Exception as exc:
                errors[0] = exc
            finally:
                connections.close_all()

        def decide_thread() -> None:
            try:
                if not holder_locked.wait(timeout=5):
                    self.fail('holder did not lock in time')
                with connections['default'].execute_wrapper(
                    _signal_before_movement_lock(decision_started),
                ):
                    decide()
            except Exception as exc:
                errors[1] = exc
            finally:
                connections.close_all()

        threads = [Thread(target=hold_thread), Thread(target=decide_thread)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        for thread in threads:
            self.assertFalse(thread.is_alive(), 'race thread did not finish')
        return errors

    def test_concurrent_candidate_edit_is_stale_not_an_error(self) -> None:
        movement, row, candidate = self._candidate_fixture()
        transaction_service = (
            ApplicationContainer().transactions.transaction_service()
        )
        original_apply = (
            transaction_service.account_service.apply_account_deltas
        )

        def hold(holder_locked: Event, decision_started: Event) -> None:
            def apply(deltas: dict[int, Decimal]) -> dict[int, Account]:
                holder_locked.set()
                if not decision_started.wait(timeout=5):
                    self.fail('decision did not start in time')
                return cast('dict[int, Account]', original_apply(deltas))

            with patch.object(
                transaction_service.account_service,
                'apply_account_deltas',
                side_effect=apply,
            ):
                transaction_service.update_transaction(
                    UpdateTransactionCommand(
                        user=self.user,
                        transaction_obj=movement,
                        account=self.account,
                        category=movement.category,
                        amount=Decimal('999.00'),
                        transaction_date=WHEN.date(),
                        type_value=TransactionType.EXPENSE,
                    ),
                )

        errors = self._run_service_race(
            hold,
            lambda: BankStatementReconciliationService().decide(
                row.pk,
                BankStatementRow.Decision.LINKED,
                self.user.pk,
                candidate.pk,
            ),
        )

        self.assertIsNone(errors[0])
        self.assertIsInstance(errors[1], StaleStatementCandidateError)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(row.transaction_id)
        movement.refresh_from_db()
        self.assertEqual(movement.amount, Decimal('999.00'))

    def test_concurrent_candidate_delete_is_stale_not_an_error(self) -> None:
        transfer, row, candidate = self._candidate_transfer_fixture()
        transfer_service = (
            ApplicationContainer().finance_account.transfer_service()
        )
        original_apply = transfer_service._balance_service.apply_account_deltas

        def hold(holder_locked: Event, decision_started: Event) -> None:
            def apply(deltas: dict[int, Decimal]) -> dict[int, Account]:
                holder_locked.set()
                if not decision_started.wait(timeout=5):
                    self.fail('decision did not start in time')
                return cast('dict[int, Account]', original_apply(deltas))

            with patch.object(
                transfer_service._balance_service,
                'apply_account_deltas',
                side_effect=apply,
            ):
                transfer_service.delete_transfer(
                    transfer_id=transfer.pk,
                    user=self.user,
                )

        errors = self._run_service_race(
            hold,
            lambda: BankStatementReconciliationService().decide(
                row.pk,
                BankStatementRow.Decision.LINKED,
                self.user.pk,
                candidate.pk,
            ),
        )

        self.assertIsNone(errors[0])
        self.assertIsInstance(errors[1], StaleStatementCandidateError)
        self.assertFalse(
            TransferMoneyLog.objects.filter(pk=transfer.pk).exists(),
        )
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(row.transfer_id)

    def test_linked_row_of_the_same_upload_does_not_deadlock_a_delete(
        self,
    ) -> None:
        """A movement already closing another row of the upload stays safe.

        The decision must take the movement before the upload and the row;
        otherwise deleting the movement (which takes it first) would wait
        for the upload while the decision waits for the movement.
        """
        movement, row, candidate = self._candidate_fixture()
        linked_row = BankStatementRow.objects.create(
            upload=row.upload,
            source_row_position=1,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            transaction=movement,
            decision=BankStatementRow.Decision.LINKED,
        )
        transaction_service = (
            ApplicationContainer().transactions.transaction_service()
        )
        balance_service = transaction_service.account_service.balance_service
        original_apply = balance_service.apply_account_deltas

        def hold(holder_locked: Event, decision_started: Event) -> None:
            def apply(deltas: dict[int, Decimal]) -> dict[int, Account]:
                holder_locked.set()
                if not decision_started.wait(timeout=5):
                    self.fail('decision did not start in time')
                return cast('dict[int, Account]', original_apply(deltas))

            with patch.object(
                balance_service,
                'apply_account_deltas',
                side_effect=apply,
            ):
                transaction_service.delete_transaction(
                    user=self.user,
                    transaction_obj=movement,
                )

        errors = self._run_service_race(
            hold,
            lambda: BankStatementReconciliationService().decide(
                row.pk,
                BankStatementRow.Decision.LINKED,
                self.user.pk,
                candidate.pk,
            ),
        )

        self.assertIsNone(errors[0])
        self.assertIsInstance(errors[1], StaleStatementCandidateError)
        self.assertFalse(
            Transaction.objects.filter(pk=movement.pk).exists(),
        )
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(row.transaction_id)
        linked_row.refresh_from_db()
        self.assertEqual(
            linked_row.decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertIsNone(linked_row.transaction_id)

    def test_deleted_candidate_movement_is_stale_not_an_error(self) -> None:
        movement, row, candidate = self._candidate_fixture()
        movement.delete()

        with self.assertRaises(StaleStatementCandidateError):
            BankStatementReconciliationService().decide(
                row.pk,
                BankStatementRow.Decision.LINKED,
                self.user.pk,
                candidate.pk,
            )

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)

    def test_concurrent_repayment_delete_does_not_deadlock_a_link(
        self,
    ) -> None:
        """The link waits for the transfer before it touches the upload.

        Deleting the transfer takes it first and only then the rows and
        uploads; a link that held the upload while waiting for the transfer
        would deadlock with it.
        """
        transfer, row = self._repayment_link_fixture()
        transfer_service = (
            ApplicationContainer().finance_account.transfer_service()
        )
        original_apply = transfer_service._balance_service.apply_account_deltas

        def hold(holder_locked: Event, decision_started: Event) -> None:
            def apply(deltas: dict[int, Decimal]) -> dict[int, Account]:
                holder_locked.set()
                if not decision_started.wait(timeout=5):
                    self.fail('decision did not start in time')
                return cast('dict[int, Account]', original_apply(deltas))

            with patch.object(
                transfer_service._balance_service,
                'apply_account_deltas',
                side_effect=apply,
            ):
                transfer_service.delete_transfer(
                    transfer_id=transfer.pk,
                    user=self.user,
                )

        link_service = ApplicationContainer().users.statement_row_link_service()
        errors = self._run_service_race(
            hold,
            lambda: link_service.link_repayment(
                row.pk,
                transfer.pk,
                self.user.pk,
            ),
        )

        self.assertIsNone(errors[0])
        self.assertIsInstance(errors[1], StaleStatementCandidateError)
        self.assertFalse(
            TransferMoneyLog.objects.filter(pk=transfer.pk).exists(),
        )
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self.assertIsNone(row.transfer_id)


class CoverageRevisionTest(TestCase):
    """ADR-0018 coverage actuality stays inside the coverage measurement."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
            file_hash='revision-file',
            total_transactions=1,
        )
        self.service = ApplicationContainer().users.statement_coverage_service()

    def test_changed_statement_period_revises_previous_coverage(self) -> None:
        first = self.service.record_statement_period(
            self.upload,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        second = self.service.record_statement_period(
            self.upload,
            date(2026, 2, 1),
            date(2026, 2, 28),
        )
        if first is None or second is None:
            self.fail('an explicit period must record coverage')
        first.refresh_from_db()

        self.assertFalse(first.is_actual)
        self.assertEqual(
            first.revision_reason,
            StatementPeriodCoverage.RevisionReason.PERIOD_REVISED,
        )
        self.assertTrue(second.is_actual)

        summary = self.service.summary(
            self.account,
            date(2026, 1, 1),
            date(2026, 2, 28),
        )
        self.assertEqual(len(summary.intervals), 1)
        self.assertEqual(summary.intervals[0].period_start, date(2026, 2, 1))
        self.assertEqual(len(summary.gaps), 1)
        self.assertEqual(summary.gaps[0].period_start, date(2026, 1, 1))
        self.assertEqual(summary.gaps[0].period_end, date(2026, 1, 31))

    def test_manual_confirmation_is_not_replaced_by_a_statement(self) -> None:
        manual = self.service.confirm_manual(
            self.user,
            self.account,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        self.service.record_statement_period(
            self.upload,
            date(2026, 2, 1),
            date(2026, 2, 28),
        )
        manual.refresh_from_db()
        self.assertTrue(manual.is_actual)
        self.assertEqual(manual.revision_reason, '')

    def test_returning_period_reactivates_exact_record(self) -> None:
        first = self.service.record_statement_period(
            self.upload,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        second = self.service.record_statement_period(
            self.upload,
            date(2026, 2, 1),
            date(2026, 2, 28),
        )
        if first is None or second is None:
            self.fail('an explicit period must record coverage')
        repeated = self.service.record_statement_period(
            self.upload,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        if repeated is None:
            self.fail('a repeated explicit period must record coverage')

        self.assertEqual(repeated.pk, first.pk)
        self.assertTrue(repeated.is_actual)
        self.assertEqual(repeated.revision_reason, '')
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_actual)
        self.assertFalse(second.is_actual)
        self.assertEqual(
            second.revision_reason,
            StatementPeriodCoverage.RevisionReason.PERIOD_REVISED,
        )
        summary = self.service.summary(
            self.account,
            date(2026, 1, 1),
            date(2026, 2, 28),
        )
        self.assertEqual(len(summary.intervals), 1)
        self.assertEqual(summary.intervals[0].period_start, date(2026, 1, 1))
        self.assertEqual(summary.intervals[0].period_end, date(2026, 1, 31))
        self.assertEqual(len(summary.gaps), 1)
        self.assertEqual(summary.gaps[0].period_start, date(2026, 2, 1))

    def test_unknown_reparsed_period_stops_confirming_previous_bounds(
        self,
    ) -> None:
        """A parse without explicit bounds retires the old confirmation."""
        first = self.service.record_statement_period(
            self.upload,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        if first is None:
            self.fail('an explicit period must record coverage')

        self.assertIsNone(
            self.service.record_statement_period(self.upload, None, None),
        )

        first.refresh_from_db()
        self.assertFalse(first.is_actual)
        self.assertEqual(
            first.revision_reason,
            StatementPeriodCoverage.RevisionReason.PERIOD_REVISED,
        )
        summary = self.service.summary(
            self.account,
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        self.assertEqual(summary.state, 'unknown')
        self.assertFalse(summary.intervals)


@override_settings(
    STATEMENT_FINGERPRINT_KEYS=KEYS,
    STATEMENT_FINGERPRINT_ACTIVE_KEY='k2',
)
class RunOwnershipTest(TransactionTestCase):
    """Only the run that owns the upload may start, finish or fail it."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def _upload(
        self,
        run_id: str,
        *,
        status: str = BankStatementUpload.Status.PENDING,
    ) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            file_hash=f'hash-{run_id}',
            pdf_file=SimpleUploadedFile(
                f'{run_id}.pdf',
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
            status=status,
            celery_task_id=run_id,
            expires_at=timezone.now() + timedelta(days=1),
        )

    def _parse_result(self) -> StatementParseResult:
        return StatementParseResult(
            transactions=[
                {
                    'date': WHEN,
                    'amount': Decimal('-100.00'),
                    'description': 'Продукты',
                    'source_ref': 'row-1',
                    'row_position': 0,
                },
            ],
            bank=SYNTHETIC_BANK,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

    def test_waiting_old_delivery_does_not_start_the_new_run(self) -> None:
        upload = self._upload('run-b')

        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            result = process_bank_statement_task.apply(
                args=[upload.pk, 'run-a'],
            ).get()

        parser.return_value.parse.assert_not_called()
        self.assertEqual(result['total_count'], 0)
        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.PENDING)
        self.assertEqual(upload.celery_task_id, 'run-b')
        self.assertEqual(upload.error_message, '')

    def test_old_delivery_cannot_fail_the_new_run(self) -> None:
        upload = self._upload(
            'run-a',
            status=BankStatementUpload.Status.PROCESSING,
        )

        def fail_with_new_owner(*_args: object, **_kwargs: object) -> None:
            BankStatementUpload.objects.filter(pk=upload.pk).update(
                celery_task_id='run-b',
                status=BankStatementUpload.Status.PENDING,
            )
            raise ValueError('bad row')

        with patch.object(
            BankStatementImportService,
            'import_statement',
            side_effect=fail_with_new_owner,
        ):
            process_bank_statement_task.apply(args=[upload.pk, 'run-a'])

        upload.refresh_from_db()
        self.assertEqual(upload.celery_task_id, 'run-b')
        self.assertEqual(upload.status, BankStatementUpload.Status.PENDING)
        self.assertEqual(upload.failed_count, 0)
        self.assertEqual(upload.error_message, '')

    def test_repeated_delivery_of_the_current_run_is_idempotent(
        self,
    ) -> None:
        upload = self._upload('run-a')

        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as parser:
            parser.return_value.parse.return_value = self._parse_result()
            first = process_bank_statement_task.apply(
                args=[upload.pk, 'run-a'],
            ).get()
            process_bank_statement_task.apply(
                args=[upload.pk, 'run-a'],
            ).get()

        self.assertEqual(first['expense_count'], 1)
        self.assertEqual(
            Transaction.objects.filter(account=self.account).count(),
            1,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))


class CoverageRunOwnershipTest(TestCase):
    """Coverage publication and retirement belong to the current run."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
            total_transactions=1,
            status=BankStatementUpload.Status.PROCESSING,
            celery_task_id='run-b',
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.service = ApplicationContainer().users.statement_coverage_service()

    def test_old_run_cannot_replace_or_retire_new_coverage(self) -> None:
        current = self.service.record_statement_period(
            self.upload,
            date(2026, 2, 1),
            date(2026, 2, 28),
            run_id='run-b',
        )
        if current is None:
            self.fail('the current run must publish its coverage')

        replaced = self.service.record_statement_period(
            self.upload,
            date(2026, 1, 1),
            date(2026, 1, 31),
            run_id='run-a',
        )
        retired = self.service.record_statement_period(
            self.upload,
            None,
            None,
            run_id='run-a',
        )

        self.assertIsNone(replaced)
        self.assertIsNone(retired)
        current.refresh_from_db()
        self.assertTrue(current.is_actual)
        self.assertEqual(current.revision_reason, '')
        self.assertFalse(
            StatementPeriodCoverage.objects.filter(
                upload=self.upload,
                period_start=date(2026, 1, 1),
            ).exists(),
        )


@override_settings(
    STATEMENT_FINGERPRINT_KEYS=KEYS,
    STATEMENT_FINGERPRINT_ACTIVE_KEY='k2',
)
class CoveragePublicationRaceTest(TransactionTestCase):
    """A run paused before publishing cannot revoke the next run's coverage."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            file_hash='paused-coverage-file',
            pdf_file=SimpleUploadedFile(
                'paused-coverage.pdf',
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
            status=BankStatementUpload.Status.PROCESSING,
            celery_task_id='run-a',
            expires_at=timezone.now() + timedelta(days=1),
        )

    def test_paused_old_run_keeps_new_coverage_actual(self) -> None:
        reached = Barrier(2, timeout=5)
        release = Barrier(2, timeout=5)
        real_record = StatementCoverageService.record_statement_period
        errors: list[Exception | None] = [None]

        def paused_record(
            service: StatementCoverageService,
            upload: BankStatementUpload,
            period_start: date | None,
            period_end: date | None,
            *,
            run_id: str | None = None,
        ) -> StatementPeriodCoverage | None:
            if run_id == 'run-a':
                reached.wait(timeout=5)
                release.wait(timeout=5)
            return real_record(
                service,
                upload,
                period_start,
                period_end,
                run_id=run_id,
            )

        def run_old() -> None:
            try:
                with patch(
                    'hasta_la_vista_money.users.services.'
                    'bank_statement_import.BankStatementParser',
                ) as parser:
                    parser.return_value.parse.return_value = (
                        StatementParseResult(
                            transactions=[
                                {
                                    'date': WHEN,
                                    'amount': Decimal('-100.00'),
                                    'description': 'Продукты',
                                    'source_ref': 'row-1',
                                    'row_position': 0,
                                },
                            ],
                            bank=SYNTHETIC_BANK,
                            period_start=date(2026, 1, 1),
                            period_end=date(2026, 1, 31),
                        )
                    )
                    process_bank_statement_task.apply(
                        args=[self.upload.pk, 'run-a'],
                    ).get()
            except Exception as exc:
                errors[0] = exc
            finally:
                connections.close_all()

        with patch.object(
            StatementCoverageService,
            'record_statement_period',
            new=paused_record,
        ):
            thread = Thread(target=run_old)
            thread.start()
            reached.wait(timeout=5)

            BankStatementUpload.objects.filter(pk=self.upload.pk).update(
                celery_task_id='run-b',
            )
            current = (
                ApplicationContainer()
                .users.statement_coverage_service()
                .record_statement_period(
                    self.upload,
                    date(2026, 2, 1),
                    date(2026, 2, 28),
                    run_id='run-b',
                )
            )
            if current is None:
                self.fail('the new run must publish its coverage')
            release.wait(timeout=5)
            thread.join(timeout=10)

        if errors[0] is not None:
            self.fail(f'old delivery failed unexpectedly: {errors[0]}')
        current.refresh_from_db()
        self.assertTrue(current.is_actual)
        self.assertFalse(
            StatementPeriodCoverage.objects.filter(
                upload=self.upload,
                period_start=date(2026, 1, 1),
            ).exists(),
        )
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.celery_task_id, 'run-b')


class LegacyCompatibilityMigrationTest(TransactionTestCase):
    """The expand/backfill marks only unproved legacy completeness."""

    migrate_from = [('users', '0029_merge_statement_branches')]
    migrate_to = [
        (
            'users',
            '0033_bankstatementupload_retention_pending_pdf_paths',
        ),
    ]

    def tearDown(self) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_backfill_marks_review_without_inventing_rows_or_money(
        self,
    ) -> None:
        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        user = User.objects.create_user(username='legacy-migration-user')
        account = Account.objects.create(
            user=user,
            name_account='Основной',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        upload_model = old_apps.get_model('users', 'BankStatementUpload')
        row_model = old_apps.get_model('users', 'BankStatementRow')

        no_evidence = upload_model.objects.create(
            user_id=user.pk,
            account_id=account.pk,
            pdf_file='completed.pdf',
            status='completed',
            total_transactions=5,
        )
        empty_parse = upload_model.objects.create(
            user_id=user.pk,
            account_id=account.pk,
            pdf_file='empty.pdf',
            status='completed',
            total_transactions=0,
        )
        legacy_skip = upload_model.objects.create(
            user_id=user.pk,
            account_id=account.pk,
            pdf_file='skipped.pdf',
            status='completed_with_unresolved',
            total_transactions=1,
        )
        row_model.objects.create(
            upload_id=legacy_skip.pk,
            source_row_position=1,
            transaction_type='expense',
            transaction_date=WHEN,
            amount=Decimal('10.00'),
            decision='skipped',
        )
        with_row = upload_model.objects.create(
            user_id=user.pk,
            account_id=account.pk,
            pdf_file='pending.pdf',
            status='completed',
            total_transactions=1,
        )
        row_model.objects.create(
            upload_id=with_row.pk,
            source_row_position=1,
            transaction_type='expense',
            transaction_date=WHEN,
            amount=Decimal('10.00'),
            decision='pending',
        )
        cleaned = upload_model.objects.create(
            user_id=user.pk,
            account_id=account.pk,
            pdf_file='cleaned.pdf',
            status='completed',
            total_transactions=3,
            statement_closing_balance=Decimal('500.00'),
            balance_discrepancy=Decimal('5.00'),
            retention_cleaned_at=WHEN,
        )
        pending = upload_model.objects.create(
            user_id=user.pk,
            account_id=account.pk,
            pdf_file='pending-run.pdf',
            status='pending',
            total_transactions=0,
        )
        transactions_before = Transaction.objects.count()
        coverage_before = StatementPeriodCoverage.objects.count()

        executor = MigrationExecutor(transaction.get_connection())
        executor.migrate(self.migrate_to)

        self.assertEqual(
            BankStatementUpload.objects.get(
                pk=no_evidence.pk,
            ).legacy_review_reason,
            BankStatementUpload.LegacyReviewReason.NO_ROW_EVIDENCE,
        )
        self.assertEqual(
            BankStatementUpload.objects.get(
                pk=empty_parse.pk,
            ).legacy_review_reason,
            BankStatementUpload.LegacyReviewReason.NO_ROW_EVIDENCE,
        )
        skipped_upload = BankStatementUpload.objects.get(pk=legacy_skip.pk)
        self.assertEqual(
            skipped_upload.legacy_review_state,
            BankStatementUpload.LegacyReviewState.REQUIRES_REVIEW,
        )
        self.assertEqual(
            skipped_upload.legacy_review_reason,
            BankStatementUpload.LegacyReviewReason.LEGACY_SKIPPED_ROWS,
        )
        self.assertEqual(
            BankStatementUpload.objects.get(pk=with_row.pk).legacy_review_state,
            BankStatementUpload.LegacyReviewState.NOT_REQUIRED,
        )
        cleaned_upload = BankStatementUpload.objects.get(pk=cleaned.pk)
        self.assertEqual(
            cleaned_upload.legacy_review_state,
            BankStatementUpload.LegacyReviewState.REQUIRES_REVIEW,
        )
        self.assertEqual(
            cleaned_upload.legacy_review_reason,
            BankStatementUpload.LegacyReviewReason.NO_ROW_EVIDENCE,
        )
        self.assertEqual(cleaned_upload.retention_cleaned_at, WHEN)
        self.assertEqual(cleaned_upload.pdf_file.name, 'cleaned.pdf')
        self.assertEqual(cleaned_upload.total_transactions, 3)
        self.assertEqual(
            cleaned_upload.statement_closing_balance,
            Decimal('500.00'),
        )
        self.assertEqual(
            cleaned_upload.balance_discrepancy,
            Decimal('5.00'),
        )
        self.assertEqual(
            BankStatementUpload.objects.get(pk=pending.pk).legacy_review_state,
            BankStatementUpload.LegacyReviewState.NOT_REQUIRED,
        )
        self.assertEqual(BankStatementRow.objects.count(), 2)
        self.assertEqual(Transaction.objects.count(), transactions_before)
        self.assertEqual(
            StatementPeriodCoverage.objects.count(),
            coverage_before,
        )
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal('1000.00'))


class LegacyReviewVisibilityTest(TestCase):
    """An unproved legacy run is visible without proving coverage."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной',
            balance=Decimal('500.00'),
            currency='RUB',
        )

    def test_accounting_control_marks_legacy_review_separately(self) -> None:
        BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='legacy.pdf',
            status=BankStatementUpload.Status.COMPLETED,
            total_transactions=4,
            statement_closing_balance=Decimal('500.00'),
            income_count=2,
            expense_count=2,
            legacy_review_state=(
                BankStatementUpload.LegacyReviewState.REQUIRES_REVIEW
            ),
            legacy_review_reason=(
                BankStatementUpload.LegacyReviewReason.NO_ROW_EVIDENCE
            ),
        )
        today = timezone.localdate()
        summary = (
            ApplicationContainer()
            .users.accounting_control_service()
            .build(
                self.account,
                today.replace(day=1),
                today,
            )
        )

        self.assertEqual(len(summary.uploads), 1)
        control = summary.uploads[0]
        self.assertTrue(control.requires_legacy_review)
        self.assertIn('Требует проверки', control.legacy_review_label)
        self.assertEqual(summary.coverage.state, 'unknown')
        self.assertEqual(summary.rows.resolved, 0)
        self.assertFalse(summary.balance.checked)
        self.assertIn('ручной', summary.adapter_note)
        self.assertNotIn('HMAC', summary.adapter_note)
        self.assertNotIn('фикстур', summary.adapter_note)
        self.assertNotIn('production', summary.adapter_note)


class TransferAuditProvenanceRetentionTest(TestCase):
    """A deleted statement transfer keeps only its safe audit identity."""

    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.account = Account.objects.create(
            user=self.user,
            name_account='РосДорБанк',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.other = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            balance=Decimal('500.00'),
            currency='RUB',
            account_number='40817810000000000001',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='statement.pdf',
            file_hash='file-a',
            expires_at=timezone.now() + timedelta(days=30),
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('100.00'),
            description='ПЕРЕВОД СЕБЕ',
            source_row_position=7,
            source_fingerprint='fingerprint-shared',
            source_fingerprint_key_version='k1',
            source_fingerprint_format_version=1,
            source_format_version=2,
            kind='own_c2c',
            counterparty_account='40817810000000000001',
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )

    def test_cleanup_scrubs_only_proved_statement_transfer_copy(self) -> None:
        markup = ApplicationContainer().users.statement_markup_service()
        markup.post_transfer(self.row.pk, self.user.pk, None)
        self.row.refresh_from_db()
        statement_transfer = self.row.transfer
        if statement_transfer is None:
            self.fail('markup did not create a statement transfer')
        transfer_service = (
            ApplicationContainer().finance_account.transfer_service()
        )
        independent = transfer_service.transfer_money(
            from_account=self.account,
            to_account=self.other,
            amount=Decimal('25.00'),
            user=self.user,
            exchange_date=WHEN,
            notes='Независимый перевод',
        )
        legacy_audit = AuditLog.objects.create(
            user=self.user,
            model_name='finance_account.TransferMoneyLog',
            object_pk='999999',
            object_name='Легаси',
            action=AuditLog.Action.CREATE,
            diff={
                'created': {
                    'amount': '77.00',
                    'notes': 'Старый легаси-перевод',
                },
            },
            kind=None,
        )
        foreign_audit = AuditLog.objects.create(
            user=self.user,
            model_name='finance_account.TransferMoneyLog',
            object_pk='888888',
            object_name='Другой',
            action=AuditLog.Action.CREATE,
            diff={
                'created': {
                    'amount': '55.00',
                    'exchange_date': WHEN.isoformat(),
                    'notes': 'Другая выписка',
                    'source_fingerprint': 'fingerprint-shared',
                    'source_file_hash': 'file-b',
                    'source_row_position': 7,
                    'from_account_id': self.other.pk,
                },
            },
            kind=AuditOperationKind.TRANSFER,
        )
        other_upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.other,
            pdf_file='other.pdf',
            file_hash='file-b',
            expires_at=timezone.now() + timedelta(days=1),
        )
        BankStatementRow.objects.create(
            upload=other_upload,
            source_row_position=7,
            source_fingerprint='fingerprint-shared',
            kind='own_c2c',
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )

        transfer_service.delete_transfer(
            transfer_id=statement_transfer.pk,
            user=self.user,
        )
        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.PENDING,
        )
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            expires_at=timezone.now(),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()

        copies = AuditLog.objects.filter(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(statement_transfer.pk),
        )
        self.assertTrue(copies.exists())
        for entry in copies:
            payload = entry.diff.get('created') or entry.diff.get('deleted')
            if not isinstance(payload, dict):
                self.fail('statement transfer audit copy lost its payload')
            self.assertNotIn('amount', payload)
            self.assertNotIn('notes', payload)
            self.assertNotIn('exchange_date', payload)
            self.assertEqual(
                payload['source_fingerprint'],
                'fingerprint-shared',
            )
            self.assertEqual(payload['source_file_hash'], 'file-a')
            self.assertEqual(payload['source_row_position'], 7)
            self.assertEqual(payload['source_format_version'], 2)

        independent_copy = AuditLog.objects.filter(
            model_name='finance_account.TransferMoneyLog',
            object_pk=str(independent.pk),
            action=AuditLog.Action.CREATE,
        ).get()
        self.assertEqual(independent_copy.diff['created']['amount'], '25.00')
        self.assertEqual(
            independent_copy.diff['created']['notes'],
            'Независимый перевод',
        )
        legacy_audit.refresh_from_db()
        foreign_audit.refresh_from_db()
        self.assertEqual(legacy_audit.diff['created']['amount'], '77.00')
        self.assertEqual(
            legacy_audit.diff['created']['notes'],
            'Старый легаси-перевод',
        )
        self.assertEqual(foreign_audit.diff['created']['amount'], '55.00')
        row = BankStatementRow.objects.get(pk=self.row.pk)
        self.assertIsNone(row.amount)
        self.assertEqual(row.description, '')
        self.assertEqual(row.source_fingerprint, 'fingerprint-shared')
        self.assertEqual(row.source_row_position, 7)

    def test_repayment_transfer_keeps_statement_provenance(self) -> None:
        """A transfer closing a repayment row carries safe bank identity."""
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.other,
            pdf_file='repayment.pdf',
            file_hash='file-c',
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=BankStatementRow.TransactionType.INCOME,
            transaction_date=WHEN,
            amount=Decimal('300.00'),
            source_row_position=9,
            source_fingerprint='repayment-fingerprint',
            source_fingerprint_key_version='k2',
            source_fingerprint_format_version=1,
            source_format_version=3,
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        transfer = (
            ApplicationContainer()
            .finance_account.transfer_service()
            .transfer_money(
                from_account=self.account,
                to_account=self.other,
                amount=Decimal('300.00'),
                user=self.user,
                exchange_date=WHEN,
                statement_row_id=row.pk,
            )
        )

        self.assertEqual(
            transfer.source_fingerprint,
            'repayment-fingerprint',
        )
        self.assertEqual(transfer.source_fingerprint_key_version, 'k2')
        self.assertEqual(transfer.source_fingerprint_format_version, 1)
        self.assertEqual(transfer.source_format_version, 3)
        self.assertEqual(transfer.source_file_hash, 'file-c')
        self.assertEqual(transfer.source_row_position, 9)

    def test_balance_metadata_survives_cleanup_without_amounts(self) -> None:
        upload = self.upload
        upload.balance_currency = 'RUB'
        upload.balance_type = BankStatementUpload.BalanceType.CLOSING_DAY
        upload.balance_bank_date = date(2026, 1, 31)
        upload.balance_result = BankStatementUpload.BalanceResult.DISCREPANCY
        upload.balance_is_actual = True
        upload.balance_reason = ''
        upload.balance_explanation_code = (
            BankStatementUpload.ExplanationCode.BANK_POSTING_DATE_DIFFERENCE
        )
        upload.balance_explained_at = timezone.now()
        upload.balance_explained_by = self.user
        upload.statement_closing_balance = Decimal('100.00')
        upload.account_balance_after = Decimal('90.00')
        upload.balance_discrepancy = Decimal('10.00')
        upload.save()
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now(),
        )

        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
        upload.refresh_from_db()

        self.assertEqual(upload.balance_currency, 'RUB')
        self.assertEqual(
            upload.balance_type,
            BankStatementUpload.BalanceType.CLOSING_DAY,
        )
        self.assertEqual(upload.balance_bank_date, date(2026, 1, 31))
        self.assertEqual(
            upload.balance_result,
            BankStatementUpload.BalanceResult.DISCREPANCY,
        )
        self.assertEqual(
            upload.balance_explanation_code,
            BankStatementUpload.ExplanationCode.BANK_POSTING_DATE_DIFFERENCE,
        )
        self.assertEqual(upload.balance_explained_by, self.user)
        self.assertIsNone(upload.statement_closing_balance)
        self.assertIsNone(upload.account_balance_after)
        self.assertIsNone(upload.balance_discrepancy)
        self.assertEqual(
            upload.balance_reason,
            BankStatementUpload.BalanceReason.BANK_DATA_CLEANED,
        )
        self.assertFalse(upload.balance_is_actual)
