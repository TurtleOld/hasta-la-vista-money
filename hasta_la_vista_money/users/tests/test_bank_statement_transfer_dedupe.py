"""Statement rows mirroring an already recorded transfer."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT_CARD,
    ACCOUNT_TYPE_DEBIT,
    ACCOUNT_TYPE_DEBIT_CARD,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
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
    StatementParseResult,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
    StaleStatementCandidateError,
)
from hasta_la_vista_money.users.tasks import process_bank_statement_task

WHEN: Final = datetime(2026, 2, 10, 12, 0, tzinfo=UTC)


class TransferDedupeBaseTest(TestCase):
    """Shared accounts, classifier, and import helpers."""

    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(
            username='transferowner',
            password='testpass123',  # nosec B106: test-only password
        )
        self.source = Account.objects.create(
            user=self.user,
            name_account='Дебет',
            type_account=ACCOUNT_TYPE_DEBIT_CARD,
            balance=Decimal('5000.00'),
            currency='RUB',
        )
        self.target = Account.objects.create(
            user=self.user,
            name_account='Накопительный',
            type_account=ACCOUNT_TYPE_DEBIT,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.card = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('0.00'),
            limit_credit=Decimal('100000.00'),
            currency='RUB',
        )
        self.service = BankStatementReconciliationService()
        classifier = MagicMock()
        classifier.classify.return_value = 'Прочее'
        ApplicationContainer.users.category_classifier.override(classifier)
        self.addCleanup(
            ApplicationContainer.users.category_classifier.reset_override,
        )

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def _create_transfer(
        self,
        *,
        from_account: Account,
        to_account: Account,
        amount: Decimal,
        when: datetime,
    ) -> TransferMoneyLog:
        return TransferMoneyLog.objects.create(
            user=self.user,
            from_account=from_account,
            to_account=to_account,
            amount=amount,
            exchange_date=when,
        )

    def _create_upload(
        self,
        account: Account,
        name: str = 'statement.pdf',
    ) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=account,
            pdf_file=SimpleUploadedFile(
                name,
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
        )

    def _import_row(
        self,
        account: Account,
        *,
        amount: Decimal,
        when: datetime,
        description: str = 'Перевод с карты',
        name: str = 'statement.pdf',
    ) -> tuple[BankStatementUpload, dict[str, int]]:
        upload = self._create_upload(account, name)
        with patch(
            'hasta_la_vista_money.users.services.bank_statement_import.'
            'BankStatementParser',
        ) as mock_parser:
            mock_parser.return_value.parse.return_value = StatementParseResult(
                transactions=[
                    {
                        'date': when,
                        'amount': amount,
                        'description': description,
                        'source_ref': 'statement-ref',
                    },
                ],
            )
            result = process_bank_statement_task.apply(args=[upload.pk]).get()
        return upload, result

    def _create_candidate_row(
        self,
        *,
        upload: BankStatementUpload,
        transfer: TransferMoneyLog | None,
        transaction: Transaction | None,
        amount: Decimal,
        when: datetime,
        type_value: str,
        position: int,
    ) -> BankStatementRow:
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=position,
            transaction_type=type_value,
            transaction_date=when,
            amount=amount,
            description='Перевод с карты',
            suggested_category='Прочее',
            decision=BankStatementRow.Decision.PENDING,
        )
        BankStatementCandidate.objects.create(
            row=row,
            transaction=transaction,
            transfer=transfer,
            description='Кандидат',
            rank=0,
        )
        return row


class OutgoingRowTransferDedupeTest(TransferDedupeBaseTest):
    """Outgoing rows are matched against the transfer source account."""

    def test_outgoing_row_matches_transfer_without_expense(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        balance_before = self.source.balance

        upload, result = self._import_row(
            self.source,
            amount=Decimal('-300.00'),
            when=WHEN,
        )

        self.assertEqual(result['expense_count'], 0)
        self.assertEqual(result['income_count'], 0)
        self.assertEqual(result['skipped_count'], 1)
        upload.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertEqual(self.source.balance, balance_before)
        self.assertFalse(
            Transaction.objects.filter(account=self.source).exists(),
        )
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)
        self.assertIsNone(row.transaction)
        self.assertIsNone(row.candidate)
        candidate = row.candidates.get()
        self.assertEqual(candidate.transfer, transfer)
        self.assertIsNone(candidate.transaction)

    def test_transfer_one_day_apart_matches(self) -> None:
        self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN - timedelta(days=1),
        )

        upload, result = self._import_row(
            self.source,
            amount=Decimal('-300.00'),
            when=WHEN,
        )

        self.assertEqual(result['expense_count'], 0)
        self.assertEqual(result['skipped_count'], 1)
        self.assertEqual(
            BankStatementRow.objects.get(upload=upload).candidates.count(),
            1,
        )

    def test_transfer_three_days_apart_does_not_match(self) -> None:
        self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN - timedelta(days=3),
        )

        upload, result = self._import_row(
            self.source,
            amount=Decimal('-300.00'),
            when=WHEN,
        )

        self.assertEqual(result['expense_count'], 1)
        self.assertEqual(result['skipped_count'], 0)
        self.assertFalse(
            BankStatementRow.objects.filter(upload=upload).exists(),
        )
        self.assertTrue(
            Transaction.objects.filter(account=self.source).exists(),
        )

    def test_transfer_from_other_account_is_not_matched(self) -> None:
        self._create_transfer(
            from_account=self.target,
            to_account=self.card,
            amount=Decimal('300.00'),
            when=WHEN,
        )

        _, result = self._import_row(
            self.source,
            amount=Decimal('-300.00'),
            when=WHEN,
        )

        self.assertEqual(result['expense_count'], 1)

    def test_transfer_linked_on_same_account_is_not_offered_again(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        first_upload = self._create_upload(self.source, 'first.pdf')
        first_row = self._create_candidate_row(
            upload=first_upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )
        first_row.transfer = transfer
        first_row.decision = BankStatementRow.Decision.LINKED
        first_row.save(update_fields=['transfer', 'decision'])

        upload, result = self._import_row(
            self.source,
            amount=Decimal('-300.00'),
            when=WHEN,
            name='second.pdf',
        )

        self.assertEqual(result['expense_count'], 1)
        self.assertFalse(
            BankStatementRow.objects.filter(upload=upload).exists(),
        )

    def test_transfer_linked_on_other_end_is_still_offered(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        target_upload = self._create_upload(self.target, 'target.pdf')
        target_row = self._create_candidate_row(
            upload=target_upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.INCOME,
            position=0,
        )
        target_row.transfer = transfer
        target_row.decision = BankStatementRow.Decision.LINKED
        target_row.save(update_fields=['transfer', 'decision'])

        upload, result = self._import_row(
            self.source,
            amount=Decimal('-300.00'),
            when=WHEN,
            name='source.pdf',
        )

        self.assertEqual(result['expense_count'], 0)
        self.assertEqual(result['skipped_count'], 1)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.candidates.get().transfer, transfer)


class IncomingRowTransferDedupeTest(TransferDedupeBaseTest):
    """Incoming non-credit rows are matched against the transfer target."""

    def test_incoming_row_matches_transfer_without_income(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('400.00'),
            when=WHEN,
        )
        balance_before = self.target.balance

        upload, result = self._import_row(
            self.target,
            amount=Decimal('400.00'),
            when=WHEN,
            description='Перевод на карту',
        )

        self.assertEqual(result['income_count'], 0)
        self.assertEqual(result['expense_count'], 0)
        self.assertEqual(result['skipped_count'], 1)
        self.target.refresh_from_db()
        self.assertEqual(self.target.balance, balance_before)
        self.assertFalse(
            Transaction.objects.filter(account=self.target).exists(),
        )
        row = BankStatementRow.objects.get(upload=upload)
        self.assertIsNone(row.candidate)
        self.assertEqual(row.candidates.get().transfer, transfer)

    def test_incoming_row_on_credit_account_stays_needs_transfer(self) -> None:
        self._create_transfer(
            from_account=self.source,
            to_account=self.card,
            amount=Decimal('400.00'),
            when=WHEN,
        )

        upload, result = self._import_row(
            self.card,
            amount=Decimal('400.00'),
            when=WHEN,
            description='Перевод на карту',
        )

        self.assertEqual(result['needs_transfer_count'], 1)
        self.assertEqual(result['income_count'], 0)
        self.assertEqual(result['skipped_count'], 0)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self.assertFalse(row.candidates.exists())


class TransferAndTransactionCandidateTest(TransferDedupeBaseTest):
    """A row can match a transaction and a transfer at the same time."""

    def test_row_shows_transaction_and_transfer_candidates(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Переводы',
            type=TransactionType.EXPENSE,
        )
        transaction = Transaction.objects.create(
            user=self.user,
            account=self.source,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('250.00'),
            date=WHEN,
            description='Перевод с карты',
        )
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('250.00'),
            when=WHEN,
        )

        upload, result = self._import_row(
            self.source,
            amount=Decimal('-250.00'),
            when=WHEN,
        )

        self.assertEqual(result['expense_count'], 0)
        row = BankStatementRow.objects.get(upload=upload)
        self.assertEqual(row.candidate, transaction)
        self.assertEqual(row.candidates.count(), 2)
        self.assertEqual(
            set(
                row.candidates.values_list('transaction_id', flat=True),
            ),
            {transaction.pk, None},
        )
        self.assertEqual(
            set(row.candidates.values_list('transfer_id', flat=True)),
            {transfer.pk, None},
        )


class TransferCandidateDecisionTest(TransferDedupeBaseTest):
    """Reconciliation decisions accept transfer candidates."""

    def test_linked_decision_links_transfer_without_movement(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        upload = self._create_upload(self.source)
        row = self._create_candidate_row(
            upload=upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )
        balance_before = self.source.balance
        candidate = row.candidates.get()

        self.service.decide(
            row.pk,
            BankStatementRow.Decision.LINKED,
            self.user.pk,
            candidate.pk,
        )

        row.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(row.transfer, transfer)
        self.assertIsNone(row.transaction)
        self.assertEqual(self.source.balance, balance_before)
        self.assertFalse(
            Transaction.objects.filter(account=self.source).exists(),
        )
        audit = row.decision_audits.get()
        self.assertEqual(audit.transfer, transfer)
        self.assertIsNone(audit.transaction)

    def test_new_decision_on_transfer_duplicate_creates_movement(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        upload = self._create_upload(self.source)
        row = self._create_candidate_row(
            upload=upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )

        self.service.decide(
            row.pk,
            BankStatementRow.Decision.NEW,
            self.user.pk,
        )

        row.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNotNone(row.transaction)
        self.assertIsNone(row.transfer)
        self.assertEqual(self.source.balance, Decimal('4700.00'))

    def test_transfer_cannot_link_two_rows_on_same_account(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        upload = self._create_upload(self.source)
        first = self._create_candidate_row(
            upload=upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )
        second = self._create_candidate_row(
            upload=upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=1,
        )
        self.service.decide(
            first.pk,
            BankStatementRow.Decision.LINKED,
            self.user.pk,
            first.candidates.get().pk,
        )

        with self.assertRaises(StaleStatementCandidateError):
            self.service.decide(
                second.pk,
                BankStatementRow.Decision.LINKED,
                self.user.pk,
                second.candidates.get().pk,
            )

        second.refresh_from_db()
        self.assertEqual(second.decision, BankStatementRow.Decision.PENDING)

    def test_transfer_closes_one_row_at_each_end(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        source_upload = self._create_upload(self.source, 'source.pdf')
        outgoing = self._create_candidate_row(
            upload=source_upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )
        target_upload = self._create_upload(self.target, 'target.pdf')
        incoming = self._create_candidate_row(
            upload=target_upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.INCOME,
            position=0,
        )

        self.service.decide(
            outgoing.pk,
            BankStatementRow.Decision.LINKED,
            self.user.pk,
            outgoing.candidates.get().pk,
        )
        self.service.decide(
            incoming.pk,
            BankStatementRow.Decision.LINKED,
            self.user.pk,
            incoming.candidates.get().pk,
        )

        outgoing.refresh_from_db()
        incoming.refresh_from_db()
        self.assertEqual(outgoing.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(incoming.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(outgoing.transfer, transfer)
        self.assertEqual(incoming.transfer, transfer)

    def test_revise_linked_transfer_to_new_creates_movement(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        upload = self._create_upload(self.source)
        row = self._create_candidate_row(
            upload=upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )
        self.service.decide(
            row.pk,
            BankStatementRow.Decision.LINKED,
            self.user.pk,
            row.candidates.get().pk,
        )

        self.service.revise_linked_to_new(row.pk, self.user.pk)

        row.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.NEW)
        self.assertIsNone(row.transfer)
        self.assertIsNotNone(row.transaction)
        self.assertEqual(self.source.balance, Decimal('4700.00'))
        audit = row.decision_audits.order_by('created_at').last()
        if audit is None:
            self.fail('Expected a revision audit entry')
        self.assertEqual(audit.previous_transfer, transfer)
        self.assertIsNone(audit.previous_transaction)

    def test_deleted_transfer_candidate_is_stale(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        upload = self._create_upload(self.source)
        row = self._create_candidate_row(
            upload=upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )
        transfer.delete()

        with self.assertRaises(StaleStatementCandidateError):
            self.service.decide(
                row.pk,
                BankStatementRow.Decision.LINKED,
                self.user.pk,
                row.candidates.get().pk,
            )

    def test_bulk_link_requires_single_current_candidate(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        upload = self._create_upload(self.source)
        row = self._create_candidate_row(
            upload=upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )

        results = self.service.bulk_decide(
            [row.pk],
            BankStatementRow.Decision.LINKED,
            self.user.pk,
            upload.pk,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].outcome, 'linked')
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.LINKED)
        self.assertEqual(row.transfer, transfer)

    def test_bulk_link_is_ambiguous_across_candidate_kinds(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Переводы',
            type=TransactionType.EXPENSE,
        )
        transaction = Transaction.objects.create(
            user=self.user,
            account=self.source,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal('300.00'),
            date=WHEN,
        )
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        upload = self._create_upload(self.source)
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=BankStatementRow.TransactionType.EXPENSE,
            transaction_date=WHEN,
            amount=Decimal('300.00'),
            description='Перевод с карты',
            suggested_category='Прочее',
            decision=BankStatementRow.Decision.PENDING,
        )
        BankStatementCandidate.objects.create(
            row=row,
            transaction=transaction,
            description='Транзакция',
            rank=0,
        )
        BankStatementCandidate.objects.create(
            row=row,
            transfer=transfer,
            description='Перевод',
            rank=1,
        )

        results = self.service.bulk_decide(
            [row.pk],
            BankStatementRow.Decision.LINKED,
            self.user.pk,
            upload.pk,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].outcome, 'ambiguous')
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.PENDING)

    def test_transfer_can_close_source_row_and_target_reminder(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.card,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        source_upload = self._create_upload(self.source, 'source.pdf')
        outgoing = self._create_candidate_row(
            upload=source_upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )
        self.service.decide(
            outgoing.pk,
            BankStatementRow.Decision.LINKED,
            self.user.pk,
            outgoing.candidates.get().pk,
        )
        card_upload = self._create_upload(self.card, 'card.pdf')
        reminder = BankStatementRow.objects.create(
            upload=card_upload,
            source_row_position=0,
            transaction_type=BankStatementRow.TransactionType.INCOME,
            transaction_date=WHEN,
            amount=Decimal('300.00'),
            description='Перевод на карту',
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )

        settled = self.service.settle_pending_transfers(self.card)

        self.assertEqual(settled, 1)
        reminder.refresh_from_db()
        self.assertEqual(
            reminder.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertEqual(reminder.transfer, transfer)

    def test_reconciliation_page_renders_transfer_candidate(self) -> None:
        transfer = self._create_transfer(
            from_account=self.source,
            to_account=self.target,
            amount=Decimal('300.00'),
            when=WHEN,
        )
        upload = self._create_upload(self.source)
        self._create_candidate_row(
            upload=upload,
            transfer=transfer,
            transaction=None,
            amount=Decimal('300.00'),
            when=WHEN,
            type_value=BankStatementRow.TransactionType.EXPENSE,
            position=0,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                'users:bank_statement_reconciliation',
                args=[upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Перевод')
        self.assertContains(response, 'Дебет → Накопительный')
