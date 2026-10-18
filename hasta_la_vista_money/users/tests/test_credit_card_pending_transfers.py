"""Tests for credit-card income ban and unperformed statement repayments."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT_CARD,
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
    BankStatementDecisionAudit,
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
    InvalidReconciliationDecisionError,
    ReconciliationDecisionConflictError,
    StaleStatementCandidateError,
)
from hasta_la_vista_money.users.services.bank_statement_retention import (
    BankStatementRetentionService,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
    StatisticsFilters,
    get_user_detailed_statistics,
)
from hasta_la_vista_money.users.tasks import process_bank_statement_task


class CreditCardStatementBaseTest(TestCase):
    """Shared setup for credit-card statement tests."""

    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(
            username='cardowner',
            password='testpass123',  # nosec B106: test-only password
        )
        self.card = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('1000.00'),
            limit_credit=Decimal('100000.00'),
            currency='RUB',
        )
        self.debit = Account.objects.create(
            user=self.user,
            name_account='Дебет',
            type_account=ACCOUNT_TYPE_DEBIT_CARD,
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.service = BankStatementReconciliationService()
        self.link_service = (
            ApplicationContainer().users.statement_row_link_service()
        )

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def _create_upload(
        self,
        account: Account | None = None,
    ) -> BankStatementUpload:
        return BankStatementUpload.objects.create(
            user=self.user,
            account=account or self.card,
            pdf_file=SimpleUploadedFile(
                'pending.pdf',
                b'%PDF-1.4 mock pdf',
                content_type='application/pdf',
            ),
        )

    def _create_pending_row(
        self,
        *,
        upload: BankStatementUpload,
        amount: Decimal,
        when: datetime,
        position: int = 0,
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=upload,
            source_row_position=position,
            transaction_type=BankStatementRow.TransactionType.INCOME,
            transaction_date=when,
            amount=amount,
            description='Перевод на карту',
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )


class CreditCardStatementImportTest(CreditCardStatementBaseTest):
    """Positive credit-card statement rows become unperformed repayments."""

    @patch(
        'hasta_la_vista_money.users.services.bank_statement.'
        '_extract_pdf_text_for_detection',
        return_value='Выписка по счёту кредитной карты',
    )
    @patch('hasta_la_vista_money.users.services.bank_statement.camelot')
    def test_credit_deposit_becomes_needs_transfer_row(
        self,
        mock_camelot: MagicMock,
        mock_detect: MagicMock,
    ) -> None:
        mock_df = pd.DataFrame(
            [
                ['18.02.2026 17:11', 'Покупка', '-85,13 ₽', '914,87 ₽'],
                ['18.02.2026 / 869838', 'MAGNIT', '', ''],
                ['09.02.2026 15:50', 'Перевод на карту', '+199,00 ₽', ''],
                ['09.02.2026 / 552183', 'Перевод от П.', '', ''],
            ],
        )
        mock_table = MagicMock()
        mock_table.df = mock_df
        mock_camelot.read_pdf.return_value = [mock_table]
        upload = self._create_upload()

        result = process_bank_statement_task.apply(args=[upload.pk]).get()

        self.assertEqual(result['income_count'], 0)
        self.assertEqual(result['expense_count'], 1)
        self.assertEqual(result['needs_transfer_count'], 1)
        upload.refresh_from_db()
        self.assertEqual(upload.needs_transfer_count, 1)
        self.assertFalse(
            Transaction.objects.filter(
                account=self.card,
                type=TransactionType.INCOME,
            ).exists(),
        )
        row = BankStatementRow.objects.get(
            upload=upload,
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self.assertEqual(row.amount, Decimal('199.00'))
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('914.87'))


class PendingTransferDismissTest(CreditCardStatementBaseTest):
    """The owner can close a reminder as not a repayment."""

    def test_mark_not_payment_closes_row_without_movement(self) -> None:
        upload = self._create_upload()
        row = self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )
        self.service.mark_not_payment(row.pk, self.user.pk)

        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.NOT_A_PAYMENT,
        )
        self.assertFalse(
            Transaction.objects.filter(account=self.card).exists(),
        )
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('1000.00'))


class ReconciliationCreditIncomeGuardTest(CreditCardStatementBaseTest):
    """Reconciliation cannot create an income on a credit account."""

    def test_new_decision_for_credit_income_rejected(self) -> None:
        upload = self._create_upload()
        category = Category.objects.create(
            user=self.user,
            name='Прочее',
            type=TransactionType.INCOME,
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            source_row_position=0,
            transaction_type=TransactionType.INCOME,
            transaction_date=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
            amount=Decimal('199.00'),
            suggested_category=category.name,
            decision=BankStatementRow.Decision.PENDING,
        )
        with self.assertRaises(InvalidReconciliationDecisionError):
            self.service.decide(
                row.pk,
                BankStatementRow.Decision.NEW,
                self.user.pk,
            )


class PendingTransferRetentionTest(CreditCardStatementBaseTest):
    """Unresolved repayments expire with the rest of the statement rows."""

    def test_expired_reminder_disappears(self) -> None:
        upload = self._create_upload()
        upload.expires_at = timezone.now() - timedelta(days=1)
        upload.save(update_fields=['expires_at'])
        row = self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )
        retention = BankStatementRetentionService(
            reconciliation_service=self.service,
        )

        cleaned = retention.cleanup_expired()

        self.assertEqual(cleaned, 1)
        row.refresh_from_db()
        self.assertEqual(row.decision, BankStatementRow.Decision.EXPIRED)
        self.assertFalse(
            self.service.pending_transfers_for_user(self.user).exists(),
        )
        upload.refresh_from_db()
        self.assertEqual(upload.needs_transfer_count, 0)


class PendingTransferStatisticsTest(CreditCardStatementBaseTest):
    """The credit-cards tab reports unperformed repayments."""

    def test_pending_count_in_statistics(self) -> None:
        upload = self._create_upload()
        self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )
        with patch(
            'django.utils.timezone.now',
            return_value=datetime(2026, 9, 26, 12, 0, tzinfo=UTC),
        ):
            stats: dict[str, Any] = dict(
                get_user_detailed_statistics(
                    self.user,
                    container=ApplicationContainer(),
                    stats_filter=StatisticsFilters(),
                ),
            )

        cards = stats['credit_cards_data']
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['pending_transfers_count'], 1)

    def test_statistics_page_shows_alert(self) -> None:
        upload = self._create_upload()
        self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('users:statistics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'непроведённых погашений')
        self.assertContains(response, 'Кредитка')


class RepaymentLinkTest(CreditCardStatementBaseTest):
    """The owner closes a repayment row by an already recorded transfer."""

    ROW_DATE = datetime(2026, 2, 9, 12, 0, tzinfo=UTC)

    def setUp(self) -> None:
        super().setUp()
        self.upload = self._create_upload()
        self.row = self._create_pending_row(
            upload=self.upload,
            amount=Decimal('199.00'),
            when=self.ROW_DATE,
        )

    def _transfer(
        self,
        *,
        amount: str = '199.00',
        when: datetime = ROW_DATE,
        to_account: Account | None = None,
    ) -> TransferMoneyLog:
        return TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=to_account or self.card,
            amount=Decimal(amount),
            exchange_date=when,
        )

    def test_candidates_match_account_amount_and_date_window(self) -> None:
        match = self._transfer(when=self.ROW_DATE + timedelta(days=1))
        self._transfer(amount='200.00')
        self._transfer(when=self.ROW_DATE + timedelta(days=2))
        other_card = Account.objects.create(
            user=self.user,
            name_account='Другая кредитка',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self._transfer(to_account=other_card)
        occupied = self._transfer()
        self._create_pending_row(
            upload=self.upload,
            amount=Decimal('199.00'),
            when=self.ROW_DATE,
            position=1,
        )
        BankStatementRow.objects.filter(
            upload=self.upload,
            source_row_position=1,
        ).update(
            transfer=occupied,
            decision=BankStatementRow.Decision.TRANSFERRED,
        )

        candidates = self.link_service.repayment_candidates([self.row])

        self.assertEqual(candidates, {self.row.pk: [match]})

    def test_link_closes_row_and_keeps_balances(self) -> None:
        transfer = self._transfer()

        self.link_service.link_repayment(self.row.pk, transfer.pk, self.user.pk)

        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertEqual(self.row.transfer_id, transfer.pk)
        self.assertTrue(
            BankStatementDecisionAudit.objects.filter(
                row=self.row,
                actor=self.user,
                decision=BankStatementRow.Decision.TRANSFERRED,
            ).exists(),
        )
        self.upload.refresh_from_db()
        self.assertEqual(self.upload.needs_transfer_count, 0)
        self.card.refresh_from_db()
        self.debit.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal('1000.00'))
        self.assertEqual(self.debit.balance, Decimal('1000.00'))

    def test_link_rejects_transfer_that_is_not_a_candidate(self) -> None:
        transfer = self._transfer(amount='200.00')

        with self.assertRaises(StaleStatementCandidateError):
            self.link_service.link_repayment(
                self.row.pk,
                transfer.pk,
                self.user.pk,
            )

        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )
        self.assertIsNone(self.row.transfer_id)

    def test_link_of_closed_row_conflicts(self) -> None:
        first = self._transfer()
        second = self._transfer()
        self.link_service.link_repayment(self.row.pk, first.pk, self.user.pk)

        with self.assertRaises(ReconciliationDecisionConflictError):
            self.link_service.link_repayment(
                self.row.pk,
                second.pk,
                self.user.pk,
            )

        self.row.refresh_from_db()
        self.assertEqual(self.row.transfer_id, first.pk)


class RepaymentLinkViewTest(CreditCardStatementBaseTest):
    """The link action is a POST of the row owner."""

    def setUp(self) -> None:
        super().setUp()
        self.upload = self._create_upload()
        self.row = self._create_pending_row(
            upload=self.upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )
        self.url = reverse(
            'users:bank_statement_pending_transfer_link',
            args=[self.upload.pk, self.row.pk],
        )

    def _transfer(self, amount: str = '199.00') -> TransferMoneyLog:
        return TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=self.card,
            amount=Decimal(amount),
            exchange_date=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )

    def test_owner_links_transfer(self) -> None:
        transfer = self._transfer()
        self.client.force_login(self.user)

        response = self.client.post(self.url, {'transfer': transfer.pk})

        self.assertRedirects(
            response,
            reverse('finance_account:list'),
            fetch_redirect_response=False,
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.transfer_id, transfer.pk)

    def test_substituted_transfer_shows_error_and_keeps_row(self) -> None:
        transfer = self._transfer(amount='200.00')
        self.client.force_login(self.user)

        response = self.client.post(
            self.url,
            {'transfer': transfer.pk},
            follow=True,
        )

        self.assertContains(response, 'Перевод не подходит для этой строки')
        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )

    def test_malformed_transfer_shows_error(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(self.url, {'transfer': 'x'}, follow=True)

        self.assertContains(response, 'Перевод не подходит для этой строки')

    def test_closed_row_conflicts(self) -> None:
        transfer = self._transfer()
        self.link_service.link_repayment(self.row.pk, transfer.pk, self.user.pk)
        self.client.force_login(self.user)

        response = self.client.post(self.url, {'transfer': transfer.pk})

        self.assertEqual(response.status_code, 409)

    def test_foreign_row_is_not_found(self) -> None:
        transfer = self._transfer()
        stranger = User.objects.create_user(
            username='stranger',
            password='testpass123',  # nosec B106: test-only password
        )
        self.client.force_login(stranger)

        response = self.client.post(self.url, {'transfer': transfer.pk})

        self.assertEqual(response.status_code, 404)
        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )


class PendingRepaymentListQueriesTest(CreditCardStatementBaseTest):
    """Repayment candidates on the accounts page are loaded in bulk."""

    WHEN = datetime(2026, 2, 9, 12, 0, tzinfo=UTC)

    def setUp(self) -> None:
        super().setUp()
        self.upload = self._create_upload()

    def _row_with_candidate(self, position: int) -> None:
        amount = Decimal('100.00') + position
        self._create_pending_row(
            upload=self.upload,
            amount=amount,
            when=self.WHEN,
            position=position,
        )
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=self.card,
            amount=amount,
            exchange_date=self.WHEN,
        )

    def _page_queries(self) -> int:
        cache.clear()
        # Without DEBUG sessions live in the cache, so log in again.
        self.client.force_login(self.user)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('finance_account:list'))
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_query_count_does_not_grow_with_rows(self) -> None:
        self._row_with_candidate(0)
        one_row = self._page_queries()

        self._row_with_candidate(1)
        self._row_with_candidate(2)

        self.assertEqual(self._page_queries(), one_row)
