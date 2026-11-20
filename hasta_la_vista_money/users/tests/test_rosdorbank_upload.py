from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from django.core.files import File
from django.test import TestCase, override_settings
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import Category, Transaction
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.tasks import (
    process_bank_statement_typed as process_bank_statement_task,
)
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    fingerprint,
    statement_identity_settings,
)

FIXTURE = Path(__file__).parent / 'fixtures' / 'rosdorbank_statement.pdf'
STATEMENT_ACCOUNT_NUMBER = '40817810000000000001'


@statement_identity_settings
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
        card = rows.get(amount=Decimal('350.00'))
        self.assertIsNone(card.source_ref)
        self.assertTrue(card.source_ref_hash)
        self.assertFalse(card.source_identity_trusted)
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

    def test_rows_keep_the_bank_calendar_day(self) -> None:
        upload = self._upload()

        card = upload.statement_rows.get(amount=Decimal('350.00'))
        self.assertEqual(card.bank_calendar_date, date(2026, 3, 1))
        self.assertEqual(
            card.date_precision,
            BankStatementRow.DatePrecision.DAY,
        )
        credit = upload.statement_rows.get(amount=Decimal('10000.00'))
        self.assertEqual(credit.bank_calendar_date, date(2026, 3, 2))

    @override_settings(TIME_ZONE='Pacific/Kiritimati')
    def test_expense_bank_day_is_kept_when_posted_elsewhere(self) -> None:
        upload = self._upload()
        row = upload.statement_rows.get(amount=Decimal('350.00'))
        category = Category.objects.create(
            user=self.user,
            name='Продукты',
            type='expense',
        )

        with timezone.override('Pacific/Pago_Pago'):
            ApplicationContainer().users.statement_markup_service().post(
                row.pk,
                self.user.pk,
                category.pk,
            )

        row.refresh_from_db()
        movement = row.transaction
        if movement is None:
            self.fail('row is not linked to a movement')
        self.assertEqual(movement.date, datetime(2026, 3, 1, tzinfo=UTC))
        self.assertEqual(movement.bank_calendar_date, date(2026, 3, 1))

    @override_settings(TIME_ZONE='Pacific/Kiritimati')
    def test_income_bank_day_is_kept_when_posted_elsewhere(self) -> None:
        upload = self._upload()
        row = upload.statement_rows.get(amount=Decimal('10000.00'))
        category = Category.objects.create(
            user=self.user,
            name='Зарплата',
            type='income',
        )

        with timezone.override('Pacific/Pago_Pago'):
            ApplicationContainer().users.statement_markup_service().post(
                row.pk,
                self.user.pk,
                category.pk,
            )

        row.refresh_from_db()
        movement = row.transaction
        if movement is None:
            self.fail('row is not linked to a movement')
        self.assertEqual(movement.date, datetime(2026, 3, 2, tzinfo=UTC))
        self.assertEqual(movement.bank_calendar_date, date(2026, 3, 2))

    @override_settings(TIME_ZONE='Pacific/Kiritimati')
    def test_own_transfer_bank_day_is_kept_when_posted_elsewhere(self) -> None:
        upload = self._upload()
        row = upload.statement_rows.get(amount=Decimal('700.00'))
        other = self._create_account('Накопительный')

        with timezone.override('Pacific/Pago_Pago'):
            ApplicationContainer().users.statement_markup_service().post_transfer(
                row.pk,
                self.user.pk,
                other.pk,
            )

        row.refresh_from_db()
        transfer = row.transfer
        if transfer is None:
            self.fail('row is not linked to a transfer')
        self.assertEqual(
            transfer.exchange_date,
            datetime(2026, 3, 2, tzinfo=UTC),
        )
        self.assertEqual(transfer.bank_calendar_date, date(2026, 3, 2))

    def test_mutual_cancel_pair_is_marked_not_posted(self) -> None:
        upload = self._upload()

        self.assertEqual(
            BankStatementRow.objects.filter(
                upload=upload,
                decision=BankStatementRow.Decision.MUTUAL_CANCEL,
            ).count(),
            2,
        )
        self.assertFalse(
            BankStatementRow.objects.filter(upload=upload)
            .exclude(source_ref=None)
            .exists(),
        )

    def test_overlapping_upload_keeps_rows_for_manual_decision(self) -> None:
        first = self._upload()
        BankStatementRow.objects.filter(
            upload=first,
            source_row_position=0,
        ).update(decision=BankStatementRow.Decision.NEW)

        second = self._upload()

        second_rows = BankStatementRow.objects.filter(upload=second)
        self.assertEqual(second_rows.count(), 10)
        self.assertEqual(second.skipped_count, 0)
        self.assertFalse(second_rows.exclude(source_ref=None).exists())
        self.assertEqual(
            set(second_rows.values_list('source_ref_hash', flat=True)),
            set(
                BankStatementRow.objects.filter(upload=first).values_list(
                    'source_ref_hash',
                    flat=True,
                ),
            ),
        )

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

    def test_retention_keeps_unmarked_rows_and_scrubs_them(self) -> None:
        upload = self._upload()
        BankStatementUpload.objects.filter(pk=upload.pk).update(
            expires_at=timezone.now(),
        )
        upload.statement_rows.update(source_ref_hash='hash')

        ApplicationContainer().users.bank_statement_retention_service().cleanup_expired()

        upload.refresh_from_db()
        self.assertEqual(
            upload.status,
            BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        rows = upload.statement_rows.all()
        self.assertEqual(
            rows.filter(
                decision=BankStatementRow.Decision.AWAITING_MARKUP,
            ).count(),
            8,
        )
        self.assertFalse(
            rows.exclude(merchant_key='', counterparty_account='').exists(),
        )
        self.assertFalse(rows.exclude(source_ref=None).exists())
        self.assertFalse(rows.filter(data_cleaned_at__isnull=True).exists())

    def test_cancel_of_debit_from_earlier_upload_stays_local_pair(self) -> None:
        first = self._upload()
        first.statement_rows.exclude(
            source_ref_hash=fingerprint(
                'rosdorbank',
                self.account.pk,
                '102-01.03.2026',
            ).digest,
        ).delete()
        first.statement_rows.update(
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )

        second = self._upload()

        # The overlapping file keeps both representations, so the cancel
        # pairs with its own debit as a mutual cancel and posts nothing.
        cancel = second.statement_rows.get(kind='cancel')
        self.assertEqual(
            cancel.decision,
            BankStatementRow.Decision.MUTUAL_CANCEL,
        )
        self.assertFalse(
            Transaction.objects.filter(account=self.account).exists(),
        )
