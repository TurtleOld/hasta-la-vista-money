"""Runtime identity decisions for bank statement rows and movements.

Synthetic parser results drive the public import task and service seams:
no real statement files, PDFs or production data are involved.
"""

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.db import OperationalError, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.utils.functional import Promise

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.repositories import AccountRepository
from hasta_la_vista_money.system.models import AuditLog, AuditOperationKind
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import (
    BankStatementCandidate,
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.repositories.statement_identity_repository import (  # noqa: E501
    StatementIdentityRepository,
)
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
    StatementParseResult,
)
from hasta_la_vista_money.users.services.bank_statement_import import (
    BankStatementImportService,
    StatementGenerationExpiredError,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    ReconciliationDecisionConflictError,
)
from hasta_la_vista_money.users.services.category_classifier import (
    NoopClassifier,
)
from hasta_la_vista_money.users.services.statement_id_fingerprint import (
    StatementIdFingerprintService,
)
from hasta_la_vista_money.users.services.statement_identity import (
    MANUAL_REASON_KEY_UNAVAILABLE,
    StatementIdentityService,
)
from hasta_la_vista_money.users.tasks import process_bank_statement_task
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    TEST_KEY_ONE_HEX,
    TEST_KEY_TWO_HEX,
    fingerprint,
)

PARSER_PATH = (
    'hasta_la_vista_money.users.services.bank_statement_import.'
    'BankStatementParser'
)
KEYS_A = '{"test-key-1": "' + TEST_KEY_ONE_HEX + '"}'
KEYS_AB = (
    '{"test-key-1": "' + TEST_KEY_ONE_HEX + '", '
    '"test-key-2": "' + TEST_KEY_TWO_HEX + '"}'
)


def transaction(
    *,
    amount: str,
    description: str = 'Операция',
    source_ref: str | None,
    position: int,
    when: datetime | None = None,
    kind: str = 'card',
) -> dict[str, Any]:
    return {
        'date': when or datetime(2026, 3, 1, 12, tzinfo=UTC),
        'amount': Decimal(amount),
        'description': description,
        'source_ref': source_ref,
        'row_position': position,
        'kind': kind,
        'merchant_key': 'SHOP',
        'counterparty_account': '',
    }


def parse_result(
    rows: list[dict[str, Any]],
    *,
    bank_code: str = constants.BANK_CODE_SBERBANK,
    requires_markup: bool = False,
    closing_balance: Decimal | None = None,
) -> StatementParseResult:
    return StatementParseResult(
        transactions=rows,
        bank_code=bank_code,
        requires_markup=requires_markup,
        closing_balance=closing_balance,
    )


def bound_connection() -> None:
    """Open a thread connection with bounded lock and statement timeouts."""
    connections.close_all()
    with connections['default'].cursor() as cursor:
        cursor.execute("SET lock_timeout = '10s'")
        cursor.execute("SET statement_timeout = '30s'")


def import_service_with_keyring(
    keys: dict[str, bytes],
    active_key_id: str,
) -> BankStatementImportService:
    """Build an import service with an explicit keyring, no global settings."""
    repository = StatementIdentityRepository()
    identity_service = StatementIdentityService(
        StatementIdFingerprintService(
            keys=keys,
            active_key_id=active_key_id,
        ),
        repository,
    )
    return BankStatementImportService(
        NoopClassifier(),
        AccountRepository(),
        identity_service,
        repository,
    )


class StatementIdentityRuntimeFixture(TestCase):
    fixtures = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Счёт',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def upload(
        self,
        name: str,
        *,
        file_hash: str | None = None,
        account: Account | None = None,
    ) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=account or self.account,
            pdf_file=f'bank_statements/{name}.pdf',
            file_hash=file_hash or name,
            status=BankStatementUpload.Status.PENDING,
        )

    def run_import(
        self,
        upload: BankStatementUpload,
        result: StatementParseResult,
    ) -> dict[str, Any]:
        parser = MagicMock()
        parser.parse.return_value = result
        with patch(PARSER_PATH, return_value=parser):
            outcome: dict[str, Any] = process_bank_statement_task.apply(
                args=[upload.pk],
            ).get()
            return outcome

    def manual_category(self) -> Category:
        return Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )

    @staticmethod
    def _parser(result: StatementParseResult) -> MagicMock:
        parser = MagicMock()
        parser.parse.return_value = result
        return MagicMock(return_value=parser)


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementIdentityRotationTest(StatementIdentityRuntimeFixture):
    def test_rotation_recognizes_old_key_and_writes_new_one(self) -> None:
        first = self.upload('first')
        self.run_import(
            first,
            parse_result(
                [
                    transaction(
                        amount='-100.00',
                        source_ref='op-1',
                        position=0,
                    ),
                    transaction(
                        amount='-200.00',
                        source_ref='op-2',
                        position=1,
                    ),
                ],
            ),
        )
        movement = Transaction.objects.get(
            source_ref_hash=(
                fingerprint('sberbank', self.account.pk, 'op-1').digest
            ),
        )
        self.assertEqual(movement.source_ref_key_id, 'test-key-1')
        self.assertIsNone(movement.source_ref)
        self.assertTrue(movement.source_identity_trusted)

        # Cleanup removes bank details but keeps the fingerprint readable.
        BankStatementUpload.objects.filter(pk=first.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()

        with override_settings(
            STATEMENT_ID_HMAC_KEYS=KEYS_AB,
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-2',
        ):
            second = self.upload('second')
            result = self.run_import(
                second,
                parse_result(
                    [
                        transaction(
                            amount='-100.00',
                            source_ref='op-1',
                            position=0,
                        ),
                        transaction(
                            amount='-300.00',
                            source_ref='op-3',
                            position=1,
                        ),
                    ],
                ),
            )
            self.assertEqual(result['skipped_count'], 1)
            new_movement = Transaction.objects.get(
                source_ref_hash=fingerprint(
                    'sberbank',
                    self.account.pk,
                    'op-3',
                    key_id='test-key-2',
                    hex_key=TEST_KEY_TWO_HEX,
                ).digest,
            )
            self.assertEqual(new_movement.source_ref_key_id, 'test-key-2')
            self.assertEqual(
                Transaction.objects.filter(amount=Decimal('100.00')).count(),
                1,
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('400.00'))

    def test_repeat_after_retention_still_matches_old_fingerprint(self) -> None:
        first = self.upload('first')
        self.run_import(
            first,
            parse_result(
                [transaction(amount='-100.00', source_ref='op-1', position=0)],
            ),
        )
        BankStatementUpload.objects.filter(pk=first.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()

        repeat = self.upload('repeat')
        result = self.run_import(
            repeat,
            parse_result(
                [transaction(amount='-100.00', source_ref='op-1', position=0)],
            ),
        )

        self.assertEqual(result['skipped_count'], 1)
        self.assertEqual(
            Transaction.objects.filter(amount=Decimal('100.00')).count(),
            1,
        )


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementIdentityMissingKeyTest(StatementIdentityRuntimeFixture):
    @override_settings(
        STATEMENT_ID_HMAC_KEYS='',
        STATEMENT_ID_HMAC_ACTIVE_KEY_ID='',
    )
    def test_missing_active_key_keeps_manual_rows_without_money(self) -> None:
        upload = self.upload('missing-key')
        result = self.run_import(
            upload,
            parse_result(
                [transaction(amount='-100.00', source_ref='op-x', position=0)],
            ),
        )

        self.assertEqual(result['expense_count'], 0)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(row.source_ref)
        self.assertIsNone(row.source_ref_hash)
        self.assertEqual(row.source_row_position, 0)
        self.assertTrue(row.candidate_description)
        self.assertFalse(Transaction.objects.exists())
        upload.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_old_worker_keyring_sees_new_stored_key_and_fails_closed(
        self,
    ) -> None:
        with override_settings(
            STATEMENT_ID_HMAC_KEYS=(
                '{"test-key-2": "' + TEST_KEY_TWO_HEX + '"}'
            ),
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-2',
        ):
            first = self.upload('new-worker')
            self.run_import(
                first,
                parse_result(
                    [
                        transaction(
                            amount='-100.00',
                            source_ref='op-b',
                            position=0,
                        ),
                    ],
                ),
            )
        self.assertTrue(Transaction.objects.exists())

        old = self.upload('old-worker')
        result = self.run_import(
            old,
            parse_result(
                [transaction(amount='-40.00', source_ref='op-a', position=0)],
            ),
        )

        self.assertEqual(result['expense_count'], 0)
        row = BankStatementRow.objects.get(upload=old)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(
            row.candidate_description,
            'Идентификатор операции не проверен: отпечаток создан '
            'недоступным ключом. Требуется ручная сверка.',
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_unknown_stored_version_blocks_automatic_posting(self) -> None:
        category = self.manual_category()
        bank_hash = fingerprint('sberbank', self.account.pk, 'old-op')
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('10.00'),
            date=timezone.now(),
            source_ref_hash=bank_hash.digest,
            source_ref_key_id=bank_hash.key_id,
            source_ref_version=2,
            source_identity_trusted=True,
        )
        upload = self.upload('unknown-version')
        result = self.run_import(
            upload,
            parse_result(
                [
                    transaction(
                        amount='-50.00',
                        source_ref='next-op',
                        position=0,
                    ),
                ],
            ),
        )

        self.assertEqual(result['expense_count'], 0)
        self.assertTrue(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.PENDING,
            ).exists(),
        )
        self.assertEqual(Transaction.objects.count(), 1)


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementIdentityLegacyTest(StatementIdentityRuntimeFixture):
    def untrusted_movement(self, ref: str) -> Transaction:
        legacy = fingerprint('legacy-unverified', self.account.pk, ref)
        return Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.manual_category(),
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            source_ref_hash=legacy.digest,
            source_ref_key_id=legacy.key_id,
            source_identity_trusted=False,
            source_file_hash=None,
            source_row_position=None,
        )

    def test_untrusted_match_is_only_a_manual_candidate(self) -> None:
        legacy = self.untrusted_movement('legacy-1')
        upload = self.upload('legacy-match')

        result = self.run_import(
            upload,
            parse_result(
                [
                    transaction(
                        amount='-100.00',
                        source_ref='legacy-1',
                        position=0,
                    ),
                ],
            ),
        )

        self.assertEqual(result['expense_count'], 0)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertTrue(row.source_identity_trusted)
        self.assertEqual(
            list(row.candidates.values_list('transaction_id', flat=True)),
            [legacy.pk],
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_nonmatch_with_legacy_history_is_not_proof_of_absence(self) -> None:
        self.untrusted_movement('legacy-1')
        upload = self.upload('legacy-nonmatch')

        result = self.run_import(
            upload,
            parse_result(
                [
                    transaction(
                        amount='-70.00',
                        source_ref='fresh-op',
                        position=0,
                    ),
                ],
            ),
        )

        self.assertEqual(result['expense_count'], 0)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIn('неподтверждённые отпечатки', row.candidate_description)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_manual_filter_excludes_hashed_records(self) -> None:
        upload = self.upload('markup')
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            amount=Decimal('100.00'),
            description='Магазин',
            source_ref=None,
            source_ref_hash=fingerprint(
                'rosdorbank',
                self.account.pk,
                '1-01.03.2026',
            ).digest,
            source_row_position=0,
            kind='card',
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        category = self.manual_category()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            source_ref=None,
            source_ref_hash=None,
        )
        hashed = fingerprint('legacy-unverified', self.account.pk, 'bank-op')
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            source_ref_hash=hashed.digest,
            source_ref_key_id=hashed.key_id,
            source_identity_trusted=False,
        )

        duplicates = (
            ApplicationContainer()
            .users.statement_markup_service()
            .probable_duplicates(upload)
        )

        self.assertEqual(list(duplicates), [row.pk])


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class RosDorSyntheticIdentityTest(StatementIdentityRuntimeFixture):
    def rows(self) -> list[dict[str, Any]]:
        return [
            transaction(
                amount='-350.00',
                description='PMP STRELKACARD13.',
                source_ref='101-01.03.2026',
                position=0,
            ),
            transaction(
                amount='-200.00',
                description='СБП перевод',
                source_ref='102-01.03.2026',
                position=1,
                kind='c2c',
            ),
        ]

    def test_another_file_with_same_reference_is_not_exact(self) -> None:
        first = self.upload('rosdor-1')
        self.run_import(
            first,
            parse_result(
                self.rows(),
                bank_code=constants.BANK_CODE_ROSDORBANK,
                requires_markup=True,
            ),
        )
        second = self.upload('rosdor-2')
        result = self.run_import(
            second,
            parse_result(
                self.rows(),
                bank_code=constants.BANK_CODE_ROSDORBANK,
                requires_markup=True,
            ),
        )

        self.assertEqual(result['skipped_count'], 0)
        self.assertEqual(second.statement_rows.count(), 2)
        first_row = first.statement_rows.first()
        second_row = second.statement_rows.first()
        if first_row is None or second_row is None:
            self.fail('overlapping upload did not keep its rows')
        self.assertEqual(first_row.source_ref_hash, second_row.source_ref_hash)
        self.assertFalse(
            BankStatementRow.objects.exclude(source_ref=None).exists(),
        )

    def test_same_file_position_stays_idempotent(self) -> None:
        upload = self.upload('rosdor-repeat')
        self.run_import(
            upload,
            parse_result(
                self.rows(),
                bank_code=constants.BANK_CODE_ROSDORBANK,
                requires_markup=True,
            ),
        )

        self.run_import(
            upload,
            parse_result(
                self.rows(),
                bank_code=constants.BANK_CODE_ROSDORBANK,
                requires_markup=True,
            ),
        )

        self.assertEqual(upload.statement_rows.count(), 2)
        self.assertFalse(Transaction.objects.exists())


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementIdentityManualPostingTest(StatementIdentityRuntimeFixture):
    def test_markup_passes_identity_without_rehashing(self) -> None:
        upload = self.upload('markup-post')
        upload.source_bank_code = constants.BANK_CODE_ROSDORBANK
        upload.save(update_fields=['source_bank_code'])
        self.run_import(
            upload,
            parse_result(
                [
                    transaction(
                        amount='-120.00',
                        source_ref='5-01.03.2026',
                        position=0,
                    ),
                ],
                bank_code=constants.BANK_CODE_ROSDORBANK,
                requires_markup=True,
            ),
        )
        row = BankStatementRow.objects.get(upload=upload)
        category = self.manual_category()

        ApplicationContainer().users.statement_markup_service().post(
            row.pk,
            self.user.pk,
            category.pk,
        )

        movement = Transaction.objects.get()
        self.assertIsNone(movement.source_ref)
        self.assertEqual(movement.source_ref_hash, row.source_ref_hash)
        self.assertEqual(movement.source_ref_key_id, row.source_ref_key_id)
        self.assertEqual(movement.source_ref_version, row.source_ref_version)
        self.assertFalse(movement.source_identity_trusted)
        self.assertEqual(movement.source_file_hash, upload.file_hash)
        self.assertEqual(movement.source_row_position, 0)
        self.assertFalse(
            AuditLog.objects.filter(diff__icontains='5-01.03.2026').exists(),
        )

    def test_reconciliation_passes_identity_without_rehashing(self) -> None:
        upload = self.upload('reconciliation-post')
        upload.source_bank_code = constants.BANK_CODE_SBERBANK
        upload.save(update_fields=['source_bank_code'])
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            amount=Decimal('80.00'),
            description='Магазин',
            suggested_category='Продукты',
            source_ref=None,
            source_ref_hash=fingerprint(
                'sberbank',
                self.account.pk,
                'recon-1',
            ).digest,
            source_ref_key_id='test-key-1',
            source_ref_version=1,
            source_identity_trusted=True,
            source_row_position=0,
            decision=BankStatementRow.Decision.PENDING,
        )

        ApplicationContainer().users.bank_statement_reconciliation_service().decide(
            row.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )

        movement = Transaction.objects.get()
        self.assertIsNone(movement.source_ref)
        self.assertEqual(movement.source_ref_hash, row.source_ref_hash)
        self.assertEqual(movement.source_ref_key_id, row.source_ref_key_id)
        self.assertTrue(movement.source_identity_trusted)
        self.assertEqual(movement.source_file_hash, upload.file_hash)
        self.assertEqual(movement.source_row_position, 0)
        self.assertFalse(
            AuditLog.objects.filter(diff__icontains='recon-1').exists(),
        )


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementIdentityRepaymentTest(StatementIdentityRuntimeFixture):
    def setUp(self) -> None:
        super().setUp()
        self.card = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('0.00'),
            limit_credit=Decimal('100000.00'),
            currency='RUB',
        )

    @override_settings(
        STATEMENT_ID_HMAC_KEYS='',
        STATEMENT_ID_HMAC_ACTIVE_KEY_ID='',
    )
    def test_repayment_row_does_not_bypass_identity_guard(self) -> None:
        upload = self.upload('repayment', account=self.card)
        result = self.run_import(
            upload,
            parse_result(
                [transaction(amount='100.00', source_ref='rep-1', position=0)],
            ),
        )

        self.assertEqual(result['needs_transfer_count'], 1)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEEDS_TRANSFER)
        self.assertIsNone(row.source_ref_hash)
        self.assertTrue(row.candidate_description)
        self.assertFalse(Transaction.objects.exists())
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('0.00'))

    def test_repayment_row_carries_identity_metadata(self) -> None:
        upload = self.upload('repayment-key', account=self.card)
        self.run_import(
            upload,
            parse_result(
                [transaction(amount='150.00', source_ref='rep-2', position=0)],
            ),
        )

        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.NEEDS_TRANSFER)
        self.assertEqual(
            row.source_ref_hash,
            fingerprint('sberbank', self.card.pk, 'rep-2').digest,
        )
        self.assertTrue(row.source_identity_trusted)


class StatementBankSnapshotTest(StatementIdentityRuntimeFixture):
    def test_snapshot_comes_from_parser_and_is_immutable(self) -> None:
        upload = self.upload('snapshot')
        self.run_import(
            upload,
            parse_result(
                [transaction(amount='-10.00', source_ref='op-1', position=0)],
            ),
        )
        upload.refresh_from_db()
        self.assertEqual(
            upload.source_bank_code,
            constants.BANK_CODE_SBERBANK,
        )

        with self.assertRaises(BankStatementParseError):
            self.run_import(
                upload,
                parse_result(
                    [
                        transaction(
                            amount='-10.00',
                            source_ref='op-1',
                            position=0,
                        ),
                    ],
                    bank_code=constants.BANK_CODE_ROSDORBANK,
                ),
            )

        upload.refresh_from_db()
        self.assertEqual(
            upload.source_bank_code,
            constants.BANK_CODE_SBERBANK,
        )


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementRetentionIdentityTest(StatementIdentityRuntimeFixture):
    def test_cleanup_preserves_fingerprint_and_scrubs_raw_audit(self) -> None:
        upload = self.upload('retention')
        upload.source_bank_code = constants.BANK_CODE_SBERBANK
        upload.save(update_fields=['source_bank_code'])
        category = self.manual_category()
        bank_hash = fingerprint('sberbank', self.account.pk, 'kept-op')
        movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('10.00'),
            date=timezone.now(),
            source_ref_hash=bank_hash.digest,
            source_ref_key_id=bank_hash.key_id,
            source_ref_version=1,
            source_identity_trusted=True,
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('10.00'),
            description='Секретно',
            source_ref=None,
            source_ref_hash=bank_hash.digest,
            source_ref_key_id=bank_hash.key_id,
            source_ref_version=1,
            source_identity_trusted=True,
            source_row_position=0,
            decision=BankStatementRow.Decision.LINKED,
            transaction=movement,
        )
        AuditLog.objects.create(
            user=self.user,
            model_name='transactions.Transaction',
            object_pk=str(movement.pk),
            action=AuditLog.Action.UPDATE,
            kind=AuditOperationKind.STATEMENT_IMPORT,
            diff={'source_ref': {'old': 'kept-op', 'new': 'kept-op'}},
        )
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()

        row.refresh_from_db()
        self.assertEqual(row.source_ref_hash, bank_hash.digest)
        self.assertEqual(row.source_ref_key_id, 'test-key-1')
        self.assertEqual(row.source_ref_version, 1)
        self.assertTrue(row.source_identity_trusted)
        self.assertEqual(row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(row.description, '')
        movement.refresh_from_db()
        self.assertEqual(movement.amount, Decimal('10.00'))
        self.assertEqual(movement.source_ref_hash, bank_hash.digest)
        self.assertFalse(
            AuditLog.objects.filter(
                model_name='transactions.Transaction',
                diff__icontains='kept-op',
            ).exists(),
        )
        self.assertTrue(
            AuditLog.objects.filter(
                object_pk='statement-audit-scrub-v1',
            ).exists(),
        )


class StatementIdentityConcurrencyTest(TransactionTestCase):
    fixtures = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Счёт',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.first = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/one.pdf',
            file_hash='one',
        )
        self.second = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/two.pdf',
            file_hash='two',
        )

    def test_two_imports_do_not_duplicate(self) -> None:
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        class SharedParser:
            def __init__(self, _path: str) -> None:
                pass

            def parse(self) -> StatementParseResult:
                barrier.wait(timeout=10)
                return parse_result(
                    [
                        transaction(
                            amount='-100.00',
                            source_ref='race-op',
                            position=0,
                        ),
                    ],
                )

        def worker(upload_id: int) -> None:
            try:
                bound_connection()
                upload = BankStatementUpload.objects.get(pk=upload_id)
                service = (
                    ApplicationContainer().users.bank_statement_import_service()
                )
                service.import_statement(upload)
            except BaseException as error:
                errors.append(error)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(upload.pk,))
            for upload in (self.first, self.second)
        ]
        with (
            patch(PARSER_PATH, SharedParser),
            override_settings(
                STATEMENT_ID_HMAC_KEYS=KEYS_A,
                STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
            ),
        ):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        for thread in threads:
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))
        self.assertFalse(
            BankStatementCandidate.objects.filter(
                transaction__isnull=True,
                transfer__isnull=True,
            ).exists(),
        )

    def test_workers_with_old_keyring_fail_closed_under_rotation(self) -> None:
        class StoredKeyParser:
            def __init__(self, _path: str) -> None:
                pass

            def parse(self) -> StatementParseResult:
                return parse_result(
                    [
                        transaction(
                            amount='-100.00',
                            source_ref='stored-b',
                            position=0,
                        ),
                    ],
                )

        with patch(PARSER_PATH, StoredKeyParser):
            import_service_with_keyring(
                {'test-key-2': bytes.fromhex(TEST_KEY_TWO_HEX)},
                'test-key-2',
            ).import_statement(self.first)

        barrier = threading.Barrier(2)
        errors: list[BaseException] = []
        old_worker_uploads = [
            BankStatementUpload.objects.create(
                user=self.user,
                account=self.account,
                pdf_file=f'bank_statements/old-{index}.pdf',
                file_hash=f'old-{index}',
            )
            for index in range(2)
        ]

        class OldWorkerParser:
            def __init__(self, _path: str) -> None:
                pass

            def parse(self) -> StatementParseResult:
                barrier.wait(timeout=10)
                return parse_result(
                    [
                        transaction(
                            amount='-50.00',
                            source_ref='new-by-old-worker',
                            position=0,
                        ),
                    ],
                )

        def worker(upload_id: int) -> None:
            try:
                bound_connection()
                upload = BankStatementUpload.objects.get(pk=upload_id)
                import_service_with_keyring(
                    {'test-key-1': bytes.fromhex(TEST_KEY_ONE_HEX)},
                    'test-key-1',
                ).import_statement(upload)
            except BaseException as error:
                errors.append(error)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(upload.pk,))
            for upload in old_worker_uploads
        ]
        with patch(PARSER_PATH, OldWorkerParser):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        for thread in threads:
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(
            BankStatementRow.objects.filter(
                decision=BankStatementRow.Decision.PENDING,
            ).count(),
            2,
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_bounded_cleanup_race_blocks_already_parsed_import(self) -> None:
        parsed = threading.Barrier(2)
        cleanup_done = threading.Barrier(2)
        errors: list[BaseException] = []

        class SlowParser:
            def __init__(self, _path: str) -> None:
                pass

            def parse(self) -> StatementParseResult:
                parsed.wait(timeout=10)
                cleanup_done.wait(timeout=10)
                return parse_result(
                    [
                        transaction(
                            amount='-100.00',
                            source_ref='cleanup-race',
                            position=0,
                        ),
                    ],
                )

        def worker() -> None:
            try:
                bound_connection()
                upload = BankStatementUpload.objects.get(pk=self.first.pk)
                import_service_with_keyring(
                    {'test-key-1': bytes.fromhex(TEST_KEY_ONE_HEX)},
                    'test-key-1',
                ).import_statement(upload)
            except BaseException as error:
                errors.append(error)
            finally:
                connections.close_all()

        thread = threading.Thread(target=worker)
        with patch(PARSER_PATH, SlowParser):
            thread.start()
            parsed.wait(timeout=10)
            BankStatementUpload.objects.filter(pk=self.first.pk).update(
                expires_at=timezone.now() - timedelta(seconds=1),
            )
            ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()
            cleanup_done.wait(timeout=10)
            thread.join(timeout=30)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], StatementGenerationExpiredError)
        self.assertFalse(Transaction.objects.exists())
        self.first.refresh_from_db()
        self.assertIsNotNone(self.first.retention_cleaned_at)


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementIdentityAccountStateGuardTest(StatementIdentityRuntimeFixture):
    def test_no_ref_row_still_respects_unreadable_stored_key(self) -> None:
        category = self.manual_category()
        retired = fingerprint('sberbank', self.account.pk, 'retired-op')
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('5.00'),
            date=timezone.now(),
            source_ref_hash=retired.digest,
            source_ref_key_id='retired-key',
            source_ref_version=1,
            source_identity_trusted=True,
        )

        upload = self.upload('no-ref-guard')
        result = self.run_import(
            upload,
            parse_result(
                [transaction(amount='-60.00', source_ref=None, position=0)],
            ),
        )

        self.assertEqual(result['expense_count'], 0)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIn('недоступным ключом', row.candidate_description)
        self.assertEqual(Transaction.objects.count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_matching_id_with_unknown_version_is_manual(self) -> None:
        category = self.manual_category()
        known = fingerprint('sberbank', self.account.pk, 'op-v99')
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('10.00'),
            date=timezone.now(),
            source_ref_hash=known.digest,
            source_ref_key_id='test-key-1',
            source_ref_version=99,
            source_identity_trusted=True,
        )

        upload = self.upload('version-99')
        result = self.run_import(
            upload,
            parse_result(
                [transaction(amount='-10.00', source_ref='op-v99', position=0)],
            ),
        )

        self.assertEqual(result['skipped_count'], 0)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_missing_active_key_with_old_key_match_is_manual(self) -> None:
        first = self.upload('old-key-write')
        self.run_import(
            first,
            parse_result(
                [transaction(amount='-20.00', source_ref='op-old', position=0)],
            ),
        )

        with override_settings(
            STATEMENT_ID_HMAC_KEYS=KEYS_AB,
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='missing-key',
        ):
            second = self.upload('missing-active')
            result = self.run_import(
                second,
                parse_result(
                    [
                        transaction(
                            amount='-20.00',
                            source_ref='op-old',
                            position=0,
                        ),
                    ],
                ),
            )

        self.assertEqual(result['skipped_count'], 0)
        row = BankStatementRow.objects.get(upload=second)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertEqual(Transaction.objects.count(), 1)


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementIdentityHashlessUncertaintyTest(StatementIdentityRuntimeFixture):
    def test_hashless_manual_row_stays_uncertain_after_resolution(self) -> None:
        first = self.upload('missing-keys')
        with override_settings(
            STATEMENT_ID_HMAC_KEYS='',
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='',
        ):
            self.run_import(
                first,
                parse_result(
                    [
                        transaction(
                            amount='-33.00',
                            source_ref='same-op',
                            position=0,
                        ),
                    ],
                ),
            )
        original = BankStatementRow.objects.get(upload=first)
        self.assertIsNone(original.source_ref_hash)
        self.assertEqual(original.source_ref_version, 0)

        second = self.upload('after-keys')
        result = self.run_import(
            second,
            parse_result(
                [
                    transaction(
                        amount='-33.00',
                        source_ref='same-op',
                        position=0,
                    ),
                ],
            ),
        )
        self.assertEqual(result['expense_count'], 0)
        self.assertTrue(
            BankStatementRow.objects.filter(
                upload=second,
                decision=BankStatementRow.Decision.PENDING,
            ).exists(),
        )
        self.assertFalse(Transaction.objects.exists())

        BankStatementRow.objects.filter(pk=original.pk).update(
            decision=BankStatementRow.Decision.EXCLUDED,
        )
        third = self.upload('after-resolution')
        result = self.run_import(
            third,
            parse_result(
                [
                    transaction(
                        amount='-44.00',
                        source_ref='fresh-op',
                        position=0,
                    ),
                ],
            ),
        )
        self.assertEqual(result['expense_count'], 0)
        self.assertFalse(Transaction.objects.exists())

    def test_genuine_manual_movement_is_not_bank_uncertainty(self) -> None:
        category = self.manual_category()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('70.00'),
            date=timezone.now(),
            source_ref=None,
            source_ref_hash=None,
            source_file_hash=None,
            source_row_position=None,
        )

        upload = self.upload('manual-movement')
        result = self.run_import(
            upload,
            parse_result(
                [transaction(amount='-15.00', source_ref=None, position=0)],
            ),
        )

        self.assertEqual(result['expense_count'], 1)
        self.assertEqual(Transaction.objects.count(), 2)


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementIdentitySameFileProofTest(StatementIdentityRuntimeFixture):
    def test_same_file_position_with_ref_is_idempotent(self) -> None:
        upload = self.upload('same-file-ref', file_hash='same-file-hash')
        category = self.manual_category()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('90.00'),
            date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            source_ref=None,
            source_ref_hash=None,
            source_file_hash=upload.file_hash,
            source_row_position=0,
        )

        result = self.run_import(
            upload,
            parse_result(
                [
                    transaction(
                        amount='-90.00',
                        source_ref='ref-new',
                        position=0,
                    ),
                ],
            ),
        )

        self.assertEqual(result['expense_count'], 0)
        self.assertEqual(result['skipped_count'], 1)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_same_file_position_applies_to_repayment_branch(self) -> None:
        card = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('0.00'),
            limit_credit=Decimal('100000.00'),
            currency='RUB',
        )
        upload = self.upload(
            'same-file-repayment',
            file_hash='same-file-repay-hash',
            account=card,
        )
        category = self.manual_category()
        Transaction.objects.create(
            user=self.user,
            account=card,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('50.00'),
            date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            source_file_hash=upload.file_hash,
            source_row_position=0,
        )

        result = self.run_import(
            upload,
            parse_result(
                [transaction(amount='50.00', source_ref='rep-new', position=0)],
            ),
        )

        self.assertEqual(result['needs_transfer_count'], 0)
        self.assertFalse(
            BankStatementRow.objects.filter(upload=upload).exists(),
        )


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementStaleGenerationTest(StatementIdentityRuntimeFixture):
    def test_parsed_job_does_not_post_after_cleanup(self) -> None:
        upload = self.upload('stale-generation')

        class CleanupDuringParse:
            def __init__(self, _path: str) -> None:
                pass

            def parse(self) -> StatementParseResult:
                ApplicationContainer().users.bank_statement_retention_service().cleanup_expired(
                    now=timezone.now() + timedelta(days=365),
                )
                return parse_result(
                    [
                        transaction(
                            amount='-25.00',
                            source_ref='stale-op',
                            position=0,
                        ),
                    ],
                )

        with (
            patch(PARSER_PATH, CleanupDuringParse),
            self.assertRaises(StatementGenerationExpiredError),
        ):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertFalse(Transaction.objects.exists())
        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertIn('повторно', upload.error_message)

    def test_localized_manual_reason_is_lazy(self) -> None:
        self.assertTrue(
            isinstance(MANUAL_REASON_KEY_UNAVAILABLE, Promise),
        )

    def test_renewed_generation_is_not_overwritten_by_old_parse(self) -> None:
        upload = self.upload('renewed-generation')
        renewed_expiry = timezone.now() + timedelta(days=99)

        class RenewDuringParse:
            def __init__(self, _path: str) -> None:
                pass

            def parse(self) -> StatementParseResult:
                BankStatementUpload.objects.filter(pk=upload.pk).update(
                    pdf_file='bank_statements/renewed.pdf',
                    expires_at=renewed_expiry,
                )
                return parse_result(
                    [
                        transaction(
                            amount='-35.00',
                            source_ref='old-generation-op',
                            position=0,
                        ),
                    ],
                )

        with patch(PARSER_PATH, RenewDuringParse):
            process_bank_statement_task.apply(args=[upload.pk])

        self.assertFalse(Transaction.objects.exists())
        upload.refresh_from_db()
        self.assertEqual(upload.pdf_file.name, 'bank_statements/renewed.pdf')
        self.assertEqual(upload.expires_at, renewed_expiry)
        self.assertNotEqual(upload.status, BankStatementUpload.Status.FAILED)


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementDuplicatePresentationTest(StatementIdentityRuntimeFixture):
    def create_representation(
        self,
        upload: BankStatementUpload,
        *,
        position: int,
        reference: str,
        amount: str = '100.00',
        duplicate_of: BankStatementRow | None = None,
        key_id: str = 'test-key-1',
        hex_key: str = TEST_KEY_ONE_HEX,
    ) -> BankStatementRow:
        identity = fingerprint(
            'sberbank',
            self.account.pk,
            reference,
            key_id=key_id,
            hex_key=hex_key,
        )
        return BankStatementRow.objects.create(
            upload=upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            amount=Decimal(amount),
            description='Магазин',
            suggested_category='Продукты',
            source_ref=None,
            source_ref_hash=identity.digest,
            source_ref_key_id=identity.key_id,
            source_ref_version=1,
            source_identity_trusted=True,
            source_row_position=position,
            duplicate_of=duplicate_of,
            decision=BankStatementRow.Decision.PENDING,
        )

    def test_import_links_pending_representation_to_root(self) -> None:
        first = self.upload('root')
        root = self.create_representation(
            first,
            position=0,
            reference='dup-op',
        )
        second = self.upload('child')
        result = self.run_import(
            second,
            parse_result(
                [
                    transaction(
                        amount='-100.00',
                        source_ref='dup-op',
                        position=0,
                    ),
                ],
            ),
        )

        self.assertEqual(result['expense_count'], 0)
        child = BankStatementRow.objects.get(upload=second)
        self.assertEqual(child.duplicate_of_id, root.pk)
        self.assertEqual(child.decision, BankStatementRow.Decision.PENDING)
        self.assertTrue(child.source_identity_trusted)
        self.assertFalse(Transaction.objects.exists())

        reconciliation = (
            ApplicationContainer().users.bank_statement_reconciliation_service()
        )
        reconciliation.decide(
            root.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )
        reconciliation.decide(
            child.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )

        child.refresh_from_db()
        root.refresh_from_db()
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(child.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(child.transaction_id, root.transaction_id)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_child_before_root_conflicts_then_links_without_money(self) -> None:
        first = self.upload('root-first')
        root = self.create_representation(
            first,
            position=0,
            reference='order-op',
        )
        second = self.upload('child-first')
        child = self.create_representation(
            second,
            position=0,
            reference='order-op',
            duplicate_of=root,
        )
        reconciliation = (
            ApplicationContainer().users.bank_statement_reconciliation_service()
        )

        with self.assertRaises(ReconciliationDecisionConflictError):
            reconciliation.decide(
                child.pk,
                BankStatementRow.Decision.NEW,
                self.user.pk,
            )
        self.assertFalse(Transaction.objects.exists())

        reconciliation.decide(
            root.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )
        reconciliation.decide(
            child.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )

        self.assertEqual(Transaction.objects.count(), 1)
        child.refresh_from_db()
        self.assertEqual(child.decision, BankStatementRow.Decision.LINKED)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_rotation_presentations_produce_one_movement(self) -> None:
        first = self.upload('rotation-root')
        root = self.create_representation(
            first,
            position=0,
            reference='rotation-op',
        )
        second = self.upload('rotation-child')
        child = self.create_representation(
            second,
            position=0,
            reference='rotation-op',
            duplicate_of=root,
            key_id='test-key-2',
            hex_key=TEST_KEY_TWO_HEX,
        )
        reconciliation = (
            ApplicationContainer().users.bank_statement_reconciliation_service()
        )

        for row in (root, child):
            reconciliation.decide(
                row.pk,
                BankStatementRow.Decision.NEW,
                self.user.pk,
            )

        self.assertEqual(Transaction.objects.count(), 1)
        child.refresh_from_db()
        self.assertEqual(child.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(
            Transaction.objects.get().source_ref_key_id,
            'test-key-1',
        )

    def test_transfer_side_is_not_occupied_by_duplicate(self) -> None:
        card = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('0.00'),
            limit_credit=Decimal('100000.00'),
            currency='RUB',
        )
        first = self.upload('repay-root', account=card)
        root = BankStatementRow.objects.create(
            upload=first,
            transaction_type=TransactionType.INCOME,
            transaction_date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            amount=Decimal('500.00'),
            description='Погашение',
            source_ref_hash=fingerprint(
                'sberbank',
                card.pk,
                'repay-op',
            ).digest,
            source_ref_key_id='test-key-1',
            source_ref_version=1,
            source_identity_trusted=True,
            source_row_position=0,
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        second = self.upload('repay-child', account=card)
        child = BankStatementRow.objects.create(
            upload=second,
            transaction_type=TransactionType.INCOME,
            transaction_date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            amount=Decimal('500.00'),
            description='Погашение',
            source_ref_hash=fingerprint(
                'sberbank',
                card.pk,
                'repay-op',
            ).digest,
            source_ref_key_id='test-key-1',
            source_ref_version=1,
            source_identity_trusted=True,
            source_row_position=0,
            duplicate_of=root,
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )

        links = ApplicationContainer().users.statement_row_link_service()
        with self.assertRaises(ValidationError):
            links.lock_repayment_row(
                child.pk,
                user_id=self.user.pk,
                to_account=card,
                amount=Decimal('500.00'),
            )


class DuplicateCycleGuardTest(StatementIdentityRuntimeFixture):
    def test_self_reference_never_posts(self) -> None:
        upload = self.upload('cycle')
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            amount=Decimal('30.00'),
            description='Магазин',
            suggested_category='Продукты',
            source_ref=None,
            source_ref_hash=fingerprint(
                'sberbank',
                self.account.pk,
                'cycle-op',
            ).digest,
            source_ref_key_id='test-key-1',
            source_ref_version=1,
            source_identity_trusted=True,
            source_row_position=0,
            decision=BankStatementRow.Decision.PENDING,
        )
        BankStatementRow.objects.filter(pk=row.pk).update(
            duplicate_of_id=row.pk,
        )
        row.refresh_from_db()

        with self.assertRaises(ReconciliationDecisionConflictError):
            ApplicationContainer().users.bank_statement_reconciliation_service().decide(
                row.pk,
                BankStatementRow.Decision.NEW,
                self.user.pk,
            )
        self.assertFalse(Transaction.objects.exists())


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class StatementIdentityManualGuardRootTest(StatementIdentityRuntimeFixture):
    def add_unrelated_legacy(self) -> None:
        legacy = fingerprint('legacy-unverified', self.account.pk, 'old-1')
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.manual_category(),
            type=TransactionType.EXPENSE,
            amount=Decimal('7.00'),
            date=timezone.now(),
            source_ref_hash=legacy.digest,
            source_ref_key_id=legacy.key_id,
            source_ref_version=1,
            source_identity_trusted=False,
        )

    def test_legacy_history_keeps_proven_duplicate_root(self) -> None:
        self.add_unrelated_legacy()
        root_upload = self.upload('guard-root')
        self.run_import(
            root_upload,
            parse_result(
                [
                    transaction(
                        amount='-60.00',
                        source_ref='guard-op',
                        position=0,
                    ),
                ],
            ),
        )
        root = BankStatementRow.objects.get(upload=root_upload)
        self.assertTrue(root.source_identity_trusted)
        self.assertIsNone(root.duplicate_of_id)

        with override_settings(
            STATEMENT_ID_HMAC_KEYS=KEYS_AB,
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-2',
        ):
            child_upload = self.upload('guard-child')
            self.run_import(
                child_upload,
                parse_result(
                    [
                        transaction(
                            amount='-60.00',
                            source_ref='guard-op',
                            position=0,
                        ),
                    ],
                ),
            )
        child = BankStatementRow.objects.get(upload=child_upload)
        self.assertEqual(child.duplicate_of_id, root.pk)
        self.assertTrue(child.source_identity_trusted)
        self.assertEqual(child.decision, BankStatementRow.Decision.PENDING)

        reconciliation = (
            ApplicationContainer().users.bank_statement_reconciliation_service()
        )
        reconciliation.decide(
            root.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )
        reconciliation.decide(
            child.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )
        self.assertEqual(
            Transaction.objects.filter(amount=Decimal('60.00')).count(),
            1,
        )
        child.refresh_from_db()
        self.assertEqual(child.decision, BankStatementRow.Decision.LINKED)

    def test_unsupported_stored_key_keeps_available_root_link(self) -> None:
        root_upload = self.upload('old-root')
        ident = fingerprint('sberbank', self.account.pk, 'old-root-op')
        root = BankStatementRow.objects.create(
            upload=root_upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=datetime(2026, 3, 1, 12, tzinfo=UTC),
            amount=Decimal('70.00'),
            description='Магазин',
            source_ref_hash=ident.digest,
            source_ref_key_id=ident.key_id,
            source_ref_version=1,
            source_identity_trusted=True,
            source_row_position=0,
            decision=BankStatementRow.Decision.PENDING,
        )
        retired = fingerprint('sberbank', self.account.pk, 'retired-2')
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.manual_category(),
            type=TransactionType.EXPENSE,
            amount=Decimal('8.00'),
            date=timezone.now(),
            source_ref_hash=retired.digest,
            source_ref_key_id='retired-key',
            source_ref_version=1,
            source_identity_trusted=True,
        )

        child_upload = self.upload('old-root-child')
        with override_settings(
            STATEMENT_ID_HMAC_KEYS=KEYS_AB,
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-2',
        ):
            self.run_import(
                child_upload,
                parse_result(
                    [
                        transaction(
                            amount='-70.00',
                            source_ref='old-root-op',
                            position=0,
                        ),
                    ],
                ),
            )
        child = BankStatementRow.objects.get(upload=child_upload)
        self.assertIsNotNone(child.candidate_description)
        self.assertEqual(child.duplicate_of_id, root.pk)


@override_settings(
    STATEMENT_ID_HMAC_KEYS=KEYS_A,
    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
)
class HashlessPostedBankUncertaintyTest(StatementIdentityRuntimeFixture):
    def test_hashless_posted_representation_stays_uncertain(self) -> None:
        with override_settings(
            STATEMENT_ID_HMAC_KEYS='',
            STATEMENT_ID_HMAC_ACTIVE_KEY_ID='',
        ):
            first = self.upload('missing-keys-post')
            self.run_import(
                first,
                parse_result(
                    [
                        transaction(
                            amount='-80.00',
                            source_ref='posted-op',
                            position=0,
                        ),
                    ],
                ),
            )
        row = BankStatementRow.objects.get(upload=first)
        self.assertIsNone(row.source_ref_hash)
        self.assertEqual(row.source_ref_version, 0)

        ApplicationContainer().users.bank_statement_reconciliation_service().decide(
            row.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )
        movement = Transaction.objects.get()
        self.assertIsNone(movement.source_ref_hash)
        self.assertEqual(movement.source_ref_version, 0)

        overlap = self.upload('missing-keys-overlap')
        result = self.run_import(
            overlap,
            parse_result(
                [
                    transaction(
                        amount='-80.00',
                        source_ref='posted-op',
                        position=0,
                        when=datetime(2026, 3, 5, 12, tzinfo=UTC),
                    ),
                ],
            ),
        )
        self.assertEqual(result['expense_count'], 0)
        self.assertTrue(
            BankStatementRow.objects.filter(
                upload=overlap,
                decision=BankStatementRow.Decision.PENDING,
            ).exists(),
        )
        self.assertEqual(Transaction.objects.count(), 1)

    def test_normal_no_id_multirow_import_still_posts(self) -> None:
        upload = self.upload('no-id-multi')
        result = self.run_import(
            upload,
            parse_result(
                [
                    transaction(amount='-10.00', source_ref=None, position=0),
                    transaction(amount='-20.00', source_ref=None, position=1),
                    transaction(amount='-30.00', source_ref=None, position=2),
                ],
            ),
        )
        self.assertEqual(result['expense_count'], 3)
        self.assertEqual(Transaction.objects.count(), 3)


class ImportFinalizationSafetyTest(StatementIdentityRuntimeFixture):
    @override_settings(
        STATEMENT_ID_HMAC_KEYS=KEYS_A,
        STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
    )
    def test_cleanup_before_finalize_keeps_bank_fields_clean(self) -> None:
        upload = self.upload('finalize-cleanup')
        original_import = BankStatementImportService.import_statement

        def import_then_cleanup(
            service: BankStatementImportService,
            target: BankStatementUpload,
            generation: Any = None,
        ) -> Any:
            result = original_import(service, target, generation=generation)
            ApplicationContainer().users.bank_statement_retention_service().cleanup_expired(
                now=timezone.now() + timedelta(days=365),
            )
            return result

        with (
            patch(
                PARSER_PATH,
                self._parser(
                    parse_result([], closing_balance=Decimal('900.00')),
                ),
            ),
            patch.object(
                BankStatementImportService,
                'import_statement',
                autospec=True,
                side_effect=import_then_cleanup,
            ),
            self.assertRaises(StatementGenerationExpiredError),
        ):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        upload.refresh_from_db()
        self.assertIsNone(upload.statement_closing_balance)
        self.assertIsNone(upload.account_balance_after)
        self.assertIsNone(upload.balance_discrepancy)
        self.assertFalse(bool(upload.pdf_file))
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertIn('повторно', upload.error_message)

    @override_settings(
        STATEMENT_ID_HMAC_KEYS=KEYS_A,
        STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
    )
    def test_replaced_generation_is_not_modified_by_old_task(self) -> None:
        upload = self.upload('finalize-replaced')
        original_import = BankStatementImportService.import_statement
        renewed_expiry = timezone.now() + timedelta(days=77)

        def import_then_renew(
            service: BankStatementImportService,
            target: BankStatementUpload,
            generation: Any = None,
        ) -> Any:
            result = original_import(service, target, generation=generation)
            BankStatementUpload.objects.filter(pk=target.pk).update(
                pdf_file='bank_statements/renewed-finalize.pdf',
                expires_at=renewed_expiry,
            )
            return result

        with (
            patch(
                PARSER_PATH,
                self._parser(
                    parse_result([], closing_balance=Decimal('950.00')),
                ),
            ),
            patch.object(
                BankStatementImportService,
                'import_statement',
                autospec=True,
                side_effect=import_then_renew,
            ),
            self.assertRaises(StatementGenerationExpiredError),
        ):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        upload.refresh_from_db()
        self.assertIsNone(upload.statement_closing_balance)
        self.assertEqual(upload.expires_at, renewed_expiry)
        self.assertEqual(
            upload.pdf_file.name,
            'bank_statements/renewed-finalize.pdf',
        )

    @override_settings(
        STATEMENT_ID_HMAC_KEYS=KEYS_A,
        STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
    )
    def test_bulk_finalize_after_cleanup_does_not_restore_sums(self) -> None:
        upload = self.upload('bulk-cleanup')
        upload.statement_closing_balance = Decimal('900.00')
        upload.save(update_fields=['statement_closing_balance'])
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()

        ApplicationContainer().users.statement_markup_service()._finalize(
            upload,
        )

        upload.refresh_from_db()
        self.assertIsNone(upload.statement_closing_balance)
        self.assertIsNone(upload.account_balance_after)
        self.assertIsNone(upload.balance_discrepancy)


class ExpiredTaskOutcomeTest(StatementIdentityRuntimeFixture):
    @override_settings(
        STATEMENT_ID_HMAC_KEYS=KEYS_A,
        STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
    )
    def test_expired_before_start_is_terminal_reupload(self) -> None:
        upload = self.upload('expired-before-start')
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        with (
            patch(PARSER_PATH, self._parser(parse_result([]))),
            self.assertRaises(StatementGenerationExpiredError),
        ):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertNotEqual(
            upload.status,
            BankStatementUpload.Status.PROCESSING,
        )
        self.assertIn('повторно', upload.error_message)
        self.assertFalse(Transaction.objects.exists())


class StatementFailureGenerationTest(StatementIdentityRuntimeFixture):
    """Failure handling keeps the generation and task that own the upload."""

    def _fail_import(
        self,
        upload: BankStatementUpload,
        *,
        task_id: str,
        side_effect: Any,
    ) -> None:
        with (
            patch(PARSER_PATH, self._parser(parse_result([]))),
            patch.object(
                BankStatementImportService,
                'import_statement',
                autospec=True,
                side_effect=side_effect,
            ),
        ):
            process_bank_statement_task.apply(
                args=[upload.pk],
                task_id=task_id,
            )

    def test_failure_after_cleanup_keeps_safe_reason(self) -> None:
        upload = self.upload('failure-after-cleanup')
        raw_bank_detail = 'счёт 40817810099910004312, перевод в аптеку'

        class CleanupThenFail:
            def __init__(self, _path: str) -> None:
                pass

            def parse(self) -> StatementParseResult:
                container = ApplicationContainer()
                service = container.users.bank_statement_retention_service()
                service.cleanup_expired(
                    now=timezone.now() + timedelta(days=365),
                )
                raise BankStatementParseError(raw_bank_detail)

        with patch(PARSER_PATH, CleanupThenFail):
            process_bank_statement_task.apply(args=[upload.pk])

        upload.refresh_from_db()
        self.assertIsNotNone(upload.retention_cleaned_at)
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertIn('повторно', upload.error_message)
        self.assertNotIn('40817810099910004312', upload.error_message)
        self.assertNotIn('аптеку', upload.error_message)

    def test_failure_of_replaced_task_keeps_new_owner(self) -> None:
        upload = self.upload('failure-replaced-owner')

        def rename_owner(
            _service: BankStatementImportService,
            target: BankStatementUpload,
            **_kwargs: Any,
        ) -> None:
            BankStatementUpload.objects.filter(pk=target.pk).update(
                status=BankStatementUpload.Status.PROCESSING,
                celery_task_id='newer-task',
            )
            raise ValueError('старый запуск упал')

        self._fail_import(
            upload,
            task_id='old-task',
            side_effect=rename_owner,
        )

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.PROCESSING)
        self.assertEqual(upload.celery_task_id, 'newer-task')
        self.assertEqual(upload.error_message, '')

    def test_failure_of_renewed_generation_is_not_written(self) -> None:
        upload = self.upload('failure-renewed-generation')
        renewed_expiry = timezone.now() + timedelta(days=11)

        def renew_then_fail(
            _service: BankStatementImportService,
            target: BankStatementUpload,
            **_kwargs: Any,
        ) -> None:
            BankStatementUpload.objects.filter(pk=target.pk).update(
                pdf_file='bank_statements/renewed-failure.pdf',
                expires_at=renewed_expiry,
                status=BankStatementUpload.Status.PENDING,
                celery_task_id='',
            )
            raise BankStatementParseError('ошибка старого файла')

        self._fail_import(
            upload,
            task_id='old-task',
            side_effect=renew_then_fail,
        )

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.PENDING)
        self.assertEqual(
            upload.pdf_file.name,
            'bank_statements/renewed-failure.pdf',
        )
        self.assertEqual(upload.expires_at, renewed_expiry)
        self.assertEqual(upload.error_message, '')

    def test_current_failure_records_the_original_message(self) -> None:
        upload = self.upload('failure-current-generation')

        def fail_current(
            _service: BankStatementImportService,
            _target: BankStatementUpload,
            **_kwargs: Any,
        ) -> None:
            raise ValueError('непредвиденная ошибка строки')

        self._fail_import(
            upload,
            task_id='current-task',
            side_effect=fail_current,
        )

        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(upload.failed_count, 1)
        self.assertIn('непредвиденная ошибка строки', upload.error_message)


class StatementFailureAtomicityTest(TransactionTestCase):
    """A renewal cannot slip between the generation check and its write."""

    fixtures = ['users.yaml']

    @staticmethod
    def _processing_upload() -> tuple[BankStatementUpload, Any, Any]:
        user = User.objects.get(pk=1)
        account = Account.objects.create(
            user=user,
            name_account='Счёт',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        upload = BankStatementUpload.objects.create(
            user=user,
            account=account,
            pdf_file='bank_statements/atomic-failure.pdf',
            file_hash='atomic-failure',
            status=BankStatementUpload.Status.PROCESSING,
            celery_task_id='old-task',
        )
        service = ApplicationContainer().users.bank_statement_import_service()
        return upload, service, service.capture_generation(upload)

    def test_renewal_waits_for_the_whole_failure_transaction(self) -> None:
        upload, service, generation = self._processing_upload()
        original_state = BankStatementImportService.generation_state
        checked = threading.Barrier(2)
        release = threading.Event()
        errors: list[BaseException] = []
        outcome: list[str] = []

        def checked_state(
            locked: BankStatementUpload,
            snapshot: Any,
        ) -> str:
            state = original_state(locked, snapshot)
            checked.wait(timeout=10)
            release.wait(timeout=10)
            return state

        def fail_current() -> None:
            try:
                bound_connection()
                outcome.append(
                    service.mark_failure_if_current(
                        upload.pk,
                        generation,
                        'old-task',
                        'старая ошибка',
                    ),
                )
            except BaseException as error:
                errors.append(error)
            finally:
                connections.close_all()

        def renew() -> None:
            try:
                bound_connection()
                with connections['default'].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '300ms'")
                BankStatementUpload.objects.filter(pk=upload.pk).update(
                    pdf_file='bank_statements/renewed-atomic.pdf',
                    expires_at=timezone.now() + timedelta(days=21),
                    status=BankStatementUpload.Status.PENDING,
                    celery_task_id='',
                    error_message='',
                )
            except BaseException as error:
                errors.append(error)
            finally:
                connections.close_all()

        with patch.object(
            BankStatementImportService,
            'generation_state',
            staticmethod(checked_state),
        ):
            worker = threading.Thread(target=fail_current)
            worker.start()
            checked.wait(timeout=10)
            renewer = threading.Thread(target=renew)
            renewer.start()
            renewer.join(timeout=20)
            release.set()
            worker.join(timeout=30)

        self.assertFalse(renewer.is_alive())
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, ['current'])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], OperationalError)
        upload.refresh_from_db()
        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertEqual(upload.error_message, 'старая ошибка')
        self.assertEqual(
            upload.pdf_file.name,
            'bank_statements/atomic-failure.pdf',
        )
