from decimal import Decimal
from pathlib import Path

from django.core.files import File
from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Transaction
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.tasks import process_bank_statement_task

FIXTURE = Path(__file__).parent / 'fixtures' / 'rosdorbank_statement.pdf'
STATEMENT_ACCOUNT_NUMBER = '40817810000000000001'


class RosDorBankUploadTest(TestCase):
    fixtures: list[str] = ['users.yaml']

    def setUp(self) -> None:
        self.user: User = User.objects.get(pk=1)
        self.account = self._create_account('РосДорБанк')

    def _create_account(
        self,
        name: str,
        account_number: str | None = None,
    ) -> Account:
        return Account.objects.create(
            user=self.user,
            name_account=name,
            balance=Decimal('1000.00'),
            currency='RUB',
            account_number=account_number,
        )

    def _upload(self, account: Account | None = None) -> BankStatementUpload:
        with FIXTURE.open('rb') as pdf:
            upload = BankStatementUpload.objects.create(
                user=self.user,
                account=account or self.account,
                pdf_file=File(pdf, name='rosdorbank.pdf'),
            )
        process_bank_statement_task.apply(args=[upload.pk])
        upload.refresh_from_db()
        return upload

    def test_rows_await_markup_and_keep_balance(self) -> None:
        upload = self._upload()

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.assertIsNone(upload.balance_discrepancy)
        rows = BankStatementRow.objects.filter(
            upload=upload,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        self.assertEqual(rows.count(), 8)
        card = rows.get(source_ref='101-01.03.2026')
        self.assertEqual(
            (
                card.kind,
                card.merchant_key,
                card.counterparty_account,
                card.amount,
                card.transaction_type,
                card.description,
            ),
            (
                'card',
                'STRELKACARD',
                '30232810000000000001',
                Decimal('350.00'),
                BankStatementRow.TransactionType.EXPENSE,
                'PMP STRELKACARD13.',
            ),
        )

    def test_mutual_cancel_pair_is_marked_not_posted(self) -> None:
        upload = self._upload()

        self.assertEqual(
            set(
                BankStatementRow.objects.filter(
                    upload=upload,
                    decision=BankStatementRow.Decision.MUTUAL_CANCEL,
                ).values_list('source_ref', flat=True),
            ),
            {'102-01.03.2026', '103-01.03.2026'},
        )

    def test_overlapping_upload_skips_known_rows(self) -> None:
        first = self._upload()
        BankStatementRow.objects.filter(
            upload=first,
            source_ref='101-01.03.2026',
        ).update(decision=BankStatementRow.Decision.NEW)
        BankStatementRow.objects.filter(
            upload=first,
            source_ref='110-03.03.2026',
        ).update(decision=BankStatementRow.Decision.EXPIRED)

        second = self._upload()

        self.assertEqual(
            list(
                BankStatementRow.objects.filter(upload=second).values_list(
                    'source_ref',
                    flat=True,
                ),
            ),
            ['110-03.03.2026'],
        )
        self.assertEqual(second.skipped_count, 9)

    def test_number_from_header_is_assigned_to_selected_account(self) -> None:
        self._upload()

        self.account.refresh_from_db()
        self.assertEqual(self.account.account_number, STATEMENT_ACCOUNT_NUMBER)

    def test_number_from_header_selects_matching_account(self) -> None:
        matching = self._create_account('Карта', STATEMENT_ACCOUNT_NUMBER)

        upload = self._upload()

        self.assertEqual(upload.account, matching)
        self.assertTrue(upload.statement_rows.exists())
        self.account.refresh_from_db()
        self.assertIsNone(self.account.account_number)

    def test_mismatched_account_number_rejects_upload(self) -> None:
        other = self._create_account('Другой', '40817810000000000099')

        upload = self._upload(other)

        self.assertEqual(upload.status, BankStatementUpload.Status.FAILED)
        self.assertIn(STATEMENT_ACCOUNT_NUMBER, upload.error_message)
        self.assertFalse(upload.statement_rows.exists())

    def test_retention_expires_unmarked_rows_and_scrubs_them(self) -> None:
        upload = self._upload()
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now(),
        )

        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()

        upload.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.COMPLETED_WITH_UNRESOLVED,
        )
        rows = upload.statement_rows.all()
        self.assertEqual(
            rows.filter(decision=BankStatementRow.Decision.EXPIRED).count(),
            8,
        )
        self.assertFalse(
            rows.exclude(merchant_key='', counterparty_account='').exists(),
        )

    def test_cancel_of_debit_from_earlier_upload_awaits_markup(self) -> None:
        first = self._upload()
        first.statement_rows.exclude(source_ref='102-01.03.2026').delete()
        first.statement_rows.update(
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )

        second = self._upload()

        cancel = second.statement_rows.get(source_ref='103-01.03.2026')
        self.assertEqual(
            cancel.decision,
            BankStatementRow.Decision.AWAITING_MARKUP,
        )
