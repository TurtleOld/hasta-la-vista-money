"""Runtime identity decisions for bank statement rows and movements.

Synthetic parser results drive the public import task and service seams:
no real statement files, PDFs or production data are involved.
"""

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
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
from hasta_la_vista_money.users.services.bank_statement import (
    BankStatementParseError,
    StatementParseResult,
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
) -> StatementParseResult:
    return StatementParseResult(
        transactions=rows,
        bank_code=bank_code,
        requires_markup=requires_markup,
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
        self.assertFalse(row.source_identity_trusted)
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
                connections.close_all()
                upload = BankStatementUpload.objects.get(pk=upload_id)
                with override_settings(
                    STATEMENT_ID_HMAC_KEYS=KEYS_A,
                    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
                ):
                    container = ApplicationContainer()
                    service = container.users.bank_statement_import_service()
                    service.import_statement(upload)
            except BaseException as error:
                errors.append(error)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(upload.pk,))
            for upload in (self.first, self.second)
        ]
        with patch(PARSER_PATH, SharedParser):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

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

        with (
            patch(PARSER_PATH, StoredKeyParser),
            override_settings(
                STATEMENT_ID_HMAC_KEYS=(
                    '{"test-key-2": "' + TEST_KEY_TWO_HEX + '"}'
                ),
                STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-2',
            ),
        ):
            ApplicationContainer().users.bank_statement_import_service().import_statement(
                self.first,
            )

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
                connections.close_all()
                upload = BankStatementUpload.objects.get(pk=upload_id)
                with override_settings(
                    STATEMENT_ID_HMAC_KEYS=KEYS_A,
                    STATEMENT_ID_HMAC_ACTIVE_KEY_ID='test-key-1',
                ):
                    container = ApplicationContainer()
                    service = container.users.bank_statement_import_service()
                    service.import_statement(upload)
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
