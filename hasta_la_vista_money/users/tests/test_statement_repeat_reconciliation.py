"""Ticket 06: repeat upload, restore and reconciliation-only imports."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any, cast
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.repositories.statement_row_repository import (
    StatementRowRepository,
)
from hasta_la_vista_money.users.services.bank_statement import (
    StatementParseResult,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    InvalidReconciliationDecisionError,
)
from hasta_la_vista_money.users.tasks import (
    process_bank_statement_typed as process_bank_statement_task,
)
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    fingerprint,
    statement_identity_settings,
)


def _transaction(
    position: int,
    *,
    amount: str = '-100.00',
    description: str = 'Покупка',
    transaction_type: str = 'expense',
    category_name: str | None = None,
) -> dict[str, Any]:
    transaction = {
        'date': timezone.now(),
        'amount': Decimal(amount),
        'description': description,
        'source_ref': None,
        'row_position': position,
        'transaction_type': transaction_type,
    }
    if category_name is not None:
        transaction['category_name'] = category_name
    return transaction


def _parser_patch(
    transactions: list[dict[str, Any]],
    *,
    bank_code: str | None = None,
    closing_balance: Decimal | None = None,
) -> Any:
    """Patch the parser facade with synthetic rows."""
    parser = MagicMock()
    parser.parse.return_value = StatementParseResult(
        transactions=list(transactions),
        bank_code=bank_code,
        closing_balance=closing_balance,
    )
    return patch(
        'hasta_la_vista_money.users.services.bank_statement_import.'
        'BankStatementParser',
        return_value=parser,
    )


class RepeatStatementUploadTestCase(TestCase):
    """Synthetic repeat uploads never create money by themselves."""

    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Повторная выписка',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Тестовая категория',
            type=TransactionType.EXPENSE,
        )
        self.upload_url = reverse(
            'finance_account:bank_statement_upload',
        )

    def _upload(
        self,
        *,
        file_hash: str = 'a' * 64,
        reconciliation_only: bool = False,
    ) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file=SimpleUploadedFile(
                'statement.pdf',
                b'%PDF-1.4 synthetic',
                content_type='application/pdf',
            ),
            file_hash=file_hash,
            reconciliation_only=reconciliation_only,
        )

    def _row(
        self,
        upload: BankStatementUpload,
        position: int,
        *,
        decision: str = BankStatementRow.Decision.PENDING,
        amount: Decimal | None = Decimal('100.00'),
        cleaned: bool = False,
        **extra: Any,
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=upload,
            source_row_position=position,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=None if cleaned else amount,
            description='' if cleaned else 'Старое описание',
            decision=decision,
            data_cleaned_at=timezone.now() if cleaned else None,
            **extra,
        )

    def test_full_reconciliation_parse_records_processing_evidence(
        self,
    ) -> None:
        upload = self._upload(reconciliation_only=True)

        with _parser_patch([_transaction(0)]) as parser:
            parser.return_value.parse.return_value.traceability_complete = True
            process_bank_statement_task.apply(args=[upload.pk]).get()

        upload.refresh_from_db()
        self.assertEqual(upload.processing_traceability_version, 1)
        self.assertIsNotNone(upload.processing_verified_at)
        self.assertEqual(upload.statement_rows.count(), 1)
        self.assertFalse(Transaction.objects.exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_repeat_upload_renews_pdf_and_forces_reconciliation_only(
        self,
    ) -> None:
        content = b'%PDF-1.4 identical repeat'
        old_deadline = timezone.now() + timedelta(days=1)

        with patch(
            'hasta_la_vista_money.finance_account.bank_statement_views.'
            'process_bank_statement_task',
        ) as task:
            task.delay.return_value = MagicMock(id='first')
            for index in range(2):
                if index:
                    BankStatementUpload.objects.update(
                        status=BankStatementUpload.Status.COMPLETED,
                    )
                self.client.force_login(self.user)
                self.client.post(
                    self.upload_url,
                    {
                        'account': self.account.pk,
                        'pdf_file': SimpleUploadedFile(
                            'statement.pdf',
                            content,
                            content_type='application/pdf',
                        ),
                    },
                )

        self.assertEqual(BankStatementUpload.objects.count(), 1)
        self.assertEqual(task.delay.call_count, 2)
        upload = BankStatementUpload.objects.get()
        self.assertTrue(upload.reconciliation_only)
        self.assertIsNone(upload.retention_cleaned_at)
        self.assertTrue(upload.pdf_file.name)
        self.assertGreater(upload.expires_at, old_deadline)
        self.assertEqual(
            task.delay.call_args_list[1].args[0],
            upload.pk,
        )

    def test_repeat_restores_all_rows_and_keeps_decisions_and_links(
        self,
    ) -> None:
        upload = self._upload(reconciliation_only=True)
        upload.expires_at = timezone.now() + timedelta(days=30)
        upload.save(update_fields=['expires_at'])
        self.user.statement_retention_days = 7
        self.user.save(update_fields=['statement_retention_days'])

        linked_movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('10.00'),
            date=timezone.now(),
            description='Связанное движение',
        )
        pending = self._row(upload, 1, cleaned=True, amount=None)
        excluded = self._row(
            upload,
            2,
            decision=BankStatementRow.Decision.EXCLUDED,
            cleaned=True,
            decision_reason='Не моя операция',
        )
        linked = self._row(
            upload,
            3,
            decision=BankStatementRow.Decision.LINKED,
            cleaned=True,
            transaction=linked_movement,
        )
        deferred = self._row(
            upload,
            4,
            decision=BankStatementRow.Decision.DEFERRED,
            cleaned=True,
            resume_decision=BankStatementRow.ResumeDecision.PENDING,
        )
        unrestored = self._row(upload, 99, cleaned=True, amount=None)

        with _parser_patch(
            [
                _transaction(1, description='Восстановленная покупка'),
                _transaction(2, description='Исключённая покупка'),
                _transaction(3, description='Связанная покупка'),
                _transaction(4, description='Отложенная покупка'),
                _transaction(5, description='Новая позиция'),
            ],
        ):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        balance = Account.objects.get(pk=self.account.pk).balance
        self.assertEqual(balance, Decimal('1000.00'))
        self.assertEqual(Transaction.objects.count(), 1)

        pending.refresh_from_db()
        excluded.refresh_from_db()
        linked.refresh_from_db()
        deferred.refresh_from_db()
        unrestored.refresh_from_db()
        self.assertEqual(
            pending.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(pending.amount, Decimal('100.00'))
        self.assertEqual(pending.description, 'Восстановленная покупка')
        self.assertIsNone(pending.data_cleaned_at)
        pending_expires_at = cast('datetime', pending.data_expires_at)
        self.assertGreater(pending_expires_at, timezone.now())
        self.assertLess(
            abs(
                pending_expires_at - (timezone.now() + timedelta(days=7)),
            ),
            timedelta(minutes=1),
        )
        self.assertEqual(
            excluded.decision,
            BankStatementRow.Decision.EXCLUDED,
        )
        self.assertEqual(excluded.decision_reason, 'Не моя операция')
        self.assertEqual(linked.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(linked.transaction_id, linked_movement.pk)
        self.assertEqual(
            deferred.decision,
            BankStatementRow.Decision.DEFERRED,
        )
        self.assertIsNone(unrestored.amount)
        self.assertIsNotNone(unrestored.data_cleaned_at)
        self.assertIsNone(unrestored.data_expires_at)
        self.assertTrue(
            BankStatementRow.objects.filter(
                upload=upload,
                source_row_position=5,
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).exists(),
        )

    def test_same_file_position_proof_links_posted_movement(self) -> None:
        upload = self._upload(reconciliation_only=True)
        movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=timezone.now(),
            description='Уже проведено',
            source_file_hash=upload.file_hash,
            source_row_position=1,
        )
        row = self._row(upload, 1, cleaned=True, amount=None)

        with _parser_patch([_transaction(1, description='Уже проведено')]):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(row.transaction_id, movement.pk)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('1000.00'),
        )

    def test_reconciliation_only_new_file_posts_no_money_until_owner_new(
        self,
    ) -> None:
        upload = self._upload(reconciliation_only=True)

        with _parser_patch(
            [
                _transaction(
                    1,
                    description='Кофе',
                    category_name='Продукты',
                ),
                _transaction(
                    2,
                    amount='250.00',
                    transaction_type='income',
                    category_name='Доход',
                ),
            ],
        ):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('1000.00'),
        )
        rows = list(
            BankStatementRow.objects.filter(upload=upload).order_by(
                'source_row_position',
            ),
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            all(
                row.decision == BankStatementRow.Decision.PENDING
                for row in rows
            ),
        )

        service = (
            ApplicationContainer().users.bank_statement_reconciliation_service()
        )
        service.decide(rows[0].pk, BankStatementRow.Decision.NEW, self.user.pk)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('900.00'),
        )

    def test_old_generation_cannot_write_after_same_file_renewal(self) -> None:
        upload = self._upload()
        service = ApplicationContainer().users.bank_statement_import_service()
        generation = service.capture_generation(upload)
        row = self._row(upload, 1, cleaned=True, amount=None)

        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now() + timedelta(days=30),
            retention_cleaned_at=None,
        )

        state = service.start_upload(upload.pk, generation, 'old-task')
        self.assertNotEqual(state, 'started')
        upload.refresh_from_db()
        row.refresh_from_db()
        self.assertNotEqual(
            upload.status,
            BankStatementUpload.Status.PROCESSING,
        )
        self.assertIsNotNone(row.data_cleaned_at)
        self.assertIsNone(row.amount)

    def test_historic_omitted_positions_are_not_invented(self) -> None:
        upload = self._upload(reconciliation_only=True)
        self._row(upload, 1, cleaned=True, amount=None)

        with _parser_patch([_transaction(1)]):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertEqual(
            BankStatementRow.objects.filter(upload=upload).count(),
            1,
        )
        self.assertFalse(
            BankStatementRow.objects.filter(
                upload=upload,
                source_row_position=2,
            ).exists(),
        )

    @statement_identity_settings
    def test_exact_bank_identifier_links_existing_movement(self) -> None:
        upload = self._upload(reconciliation_only=True)
        upload.source_bank_code = 'sberbank'
        upload.save(update_fields=['source_bank_code'])
        source_ref = 'AUTH-42'
        digest = fingerprint(
            'sberbank',
            self.account.pk,
            source_ref,
        )
        movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=timezone.now(),
            description='Уже проведено по ID',
            source_ref_hash=digest.digest,
            source_ref_key_id=digest.key_id,
            source_ref_version=digest.version,
            source_identity_trusted=True,
        )
        transaction = _transaction(1, description='Уже проведено по ID')
        transaction['source_ref'] = source_ref

        with _parser_patch([transaction], bank_code='sberbank'):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        row = BankStatementRow.objects.get(
            upload=upload,
            source_row_position=1,
        )
        self.assertEqual(row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(row.transaction_id, movement.pk)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('1000.00'),
        )

    def test_parser_fix_recovers_parse_error_without_posting(self) -> None:
        upload = self._upload(reconciliation_only=True)
        row = self._row(
            upload,
            1,
            decision=BankStatementRow.Decision.PARSE_ERROR,
            cleaned=True,
            amount=None,
            parse_error_code=BankStatementRow.ParseError.MISSING_AMOUNT,
        )

        with _parser_patch([_transaction(1, description='Теперь разобрано')]):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(row.parse_error_code, '')
        self.assertEqual(row.amount, Decimal('100.00'))
        self.assertFalse(Transaction.objects.exists())

    def test_similar_movement_is_not_a_guessed_match(self) -> None:
        upload = self._upload(reconciliation_only=True)
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=timezone.now(),
            description='Похожая операция',
        )

        with _parser_patch([_transaction(1, description='Покупка')]):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        row = BankStatementRow.objects.get(
            upload=upload,
            source_row_position=1,
        )
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNone(row.transaction_id)
        self.assertFalse(row.candidates.exists())

    def test_restored_rows_expire_on_their_own_new_deadline(self) -> None:
        upload = self._upload(reconciliation_only=True)
        row = self._row(upload, 1, cleaned=True, amount=None)

        with _parser_patch([_transaction(1)]):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        row.refresh_from_db()
        upload.refresh_from_db()
        deadline = cast('datetime', row.data_expires_at)
        service = (
            ApplicationContainer().users.bank_statement_retention_service()
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(
                service.cleanup_expired(deadline + timedelta(seconds=1)),
                1,
            )

        row.refresh_from_db()
        upload.refresh_from_db()
        self.assertIsNone(row.amount)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertIsNotNone(row.data_cleaned_at)
        self.assertFalse(bool(upload.pdf_file))
        self.assertFalse(Transaction.objects.exists())

    def _legacy_cleaned_row(
        self,
        upload: BankStatementUpload,
        *,
        position: int | None = None,
        decision: str = BankStatementRow.Decision.PENDING,
        transaction: Transaction | None = None,
    ) -> BankStatementRow:
        """A row cleaned only through the old upload marker."""
        return BankStatementRow.objects.create(
            upload=upload,
            source_row_position=position,
            transaction_type=None,
            transaction_date=None,
            amount=None,
            description='',
            decision=decision,
            transaction=transaction,
            data_cleaned_at=None,
            data_expires_at=None,
        )

    @staticmethod
    def _mark_legacy_upload_cleaned(
        upload: BankStatementUpload,
        marker: datetime,
    ) -> None:
        upload.retention_cleaned_at = marker
        upload.expires_at = marker
        upload.status = BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED
        upload.pdf_file.delete(save=False)
        upload.pdf_file = ''
        upload.save(
            update_fields=[
                'retention_cleaned_at',
                'expires_at',
                'status',
                'pdf_file',
            ],
        )

    def test_public_repeat_stamps_legacy_rows_before_upload_reset(
        self,
    ) -> None:
        content = b'%PDF-1.4 legacy repeat'
        file_hash = sha256(content).hexdigest()
        upload = self._upload(file_hash=file_hash)
        old_marker = timezone.now() - timedelta(days=5)
        self._mark_legacy_upload_cleaned(upload, old_marker)
        linked_movement = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('10.00'),
            date=timezone.now(),
            description='Связанное движение',
        )
        unmatched = self._legacy_cleaned_row(upload)
        matched = self._legacy_cleaned_row(upload, position=1)
        linked = self._legacy_cleaned_row(
            upload,
            decision=BankStatementRow.Decision.LINKED,
            transaction=linked_movement,
        )

        with (
            patch(
                'hasta_la_vista_money.finance_account.bank_statement_views.'
                'process_bank_statement_task',
            ) as task,
            _parser_patch([_transaction(1, description='Восстановлено')]),
        ):
            task.delay.return_value = MagicMock(id='repeat')
            self.client.force_login(self.user)
            response = self.client.post(
                self.upload_url,
                {
                    'account': self.account.pk,
                    'pdf_file': SimpleUploadedFile(
                        'legacy.pdf',
                        content,
                        content_type='application/pdf',
                    ),
                },
            )
            self.assertEqual(response.status_code, 302)
            task.delay.assert_called_once_with(upload.pk)

            upload.refresh_from_db()
            self.assertTrue(upload.reconciliation_only)
            self.assertIsNone(upload.retention_cleaned_at)
            self.assertGreater(upload.expires_at, old_marker)
            for row in (unmatched, matched, linked):
                row.refresh_from_db()
                self.assertEqual(row.data_cleaned_at, old_marker)

            process_bank_statement_task.apply(args=[upload.pk]).get()

        matched.refresh_from_db()
        unmatched.refresh_from_db()
        linked.refresh_from_db()
        upload.refresh_from_db()
        self.assertIsNone(matched.data_cleaned_at)
        self.assertGreater(
            cast('datetime', matched.data_expires_at),
            timezone.now(),
        )
        self.assertEqual(matched.amount, Decimal('100.00'))
        self.assertEqual(matched.description, 'Восстановлено')
        self.assertEqual(matched.source_row_position, 1)
        self.assertEqual(
            matched.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(
            unmatched.data_cleaned_at,
            old_marker,
        )
        self.assertIsNone(unmatched.data_expires_at)
        self.assertIsNone(unmatched.source_row_position)
        self.assertIsNone(unmatched.source_ref_hash)
        self.assertIsNone(unmatched.amount)
        self.assertEqual(unmatched.description, '')
        self.assertEqual(
            unmatched.decision,
            BankStatementRow.Decision.PENDING,
        )
        self.assertFalse(
            BankStatementRow.objects.filter(
                StatementRowRepository.bank_data_available_q(),
                pk=unmatched.pk,
            ).exists(),
        )
        self.assertTrue(
            BankStatementRow.objects.filter(
                StatementRowRepository.bank_data_available_q(),
                pk=matched.pk,
            ).exists(),
        )
        self.assertEqual(linked.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(linked.transaction_id, linked_movement.pk)
        self.assertEqual(
            BankStatementUpload.objects.filter(pk=upload.pk).count(),
            1,
        )
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('1000.00'),
        )
        self.assertEqual(Transaction.objects.count(), 1)

    def test_repeat_never_compares_bank_balance_with_current_balance(
        self,
    ) -> None:
        upload = self._upload(reconciliation_only=True)

        with _parser_patch(
            [_transaction(1)],
            closing_balance=Decimal('9000.00'),
        ):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        upload.refresh_from_db()
        self.assertEqual(
            upload.statement_closing_balance,
            Decimal('9000.00'),
        )
        self.assertIsNone(upload.account_balance_after)
        self.assertIsNone(upload.balance_discrepancy)
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('1000.00'),
        )
        self.assertFalse(Transaction.objects.exists())

    def test_unknown_category_routes_to_markup_then_posts(self) -> None:
        upload = self._upload(reconciliation_only=True)
        transaction = _transaction(1, description='Неизвестный магазин')

        with _parser_patch([transaction]):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        row = BankStatementRow.objects.get(
            upload=upload,
            source_row_position=1,
        )
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(row.suggested_category, '')
        self.assertFalse(Category.objects.filter(name='').exists())
        self.assertFalse(Transaction.objects.exists())
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('1000.00'),
        )

        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type=TransactionType.EXPENSE,
        )
        markup_service = ApplicationContainer().users.statement_markup_service()
        markup_service.post(row.pk, self.user.pk, category.pk)

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(row.transaction_id)
        movement = row.transaction
        if movement is None:
            self.fail('posted row has no movement')
        self.assertEqual(movement.category_id, category.pk)
        self.assertEqual(movement.amount, Decimal('100.00'))
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('900.00'),
        )
        self.assertTrue(
            row.decision_audits.filter(
                decision=BankStatementRow.Decision.NEW,
            ).exists(),
        )
        self.assertTrue(
            AuditLog.objects.filter(
                model_name='transactions.Transaction',
                object_pk=str(movement.pk),
            ).exists(),
        )

        with _parser_patch([transaction]):
            process_bank_statement_task.apply(args=[upload.pk]).get()

        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertEqual(row.transaction_id, movement.pk)
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('900.00'),
        )
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertFalse(Category.objects.filter(name='').exists())

    def test_new_decision_rejects_missing_category_without_money(self) -> None:
        upload = self._upload(reconciliation_only=True)
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=1,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=timezone.now(),
            amount=Decimal('100.00'),
            description='Без категории',
            suggested_category='',
            decision=BankStatementRow.Decision.PENDING,
        )
        service = (
            ApplicationContainer().users.bank_statement_reconciliation_service()
        )

        with self.assertRaises(InvalidReconciliationDecisionError) as raised:
            service.decide(
                row.pk,
                BankStatementRow.Decision.NEW,
                self.user.pk,
            )

        self.assertEqual(str(raised.exception), 'category')
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(Category.objects.filter(name='').exists())
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(row.transaction_id)
        self.assertEqual(
            Account.objects.get(pk=self.account.pk).balance,
            Decimal('1000.00'),
        )

    def test_upload_form_selects_reconciliation_only_for_new_file(self) -> None:
        with patch(
            'hasta_la_vista_money.finance_account.bank_statement_views.'
            'process_bank_statement_task',
        ) as task:
            task.delay.return_value = MagicMock(id='task')
            self.client.force_login(self.user)
            response = self.client.post(
                self.upload_url,
                {
                    'account': self.account.pk,
                    'reconciliation_only': 'on',
                    'pdf_file': SimpleUploadedFile(
                        'new.pdf',
                        b'%PDF-1.4 brand new',
                        content_type='application/pdf',
                    ),
                },
            )

        self.assertEqual(response.status_code, 302)
        upload = BankStatementUpload.objects.get()
        self.assertTrue(upload.reconciliation_only)
        task.delay.assert_called_once()
