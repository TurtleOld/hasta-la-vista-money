"""Tests for credit-card income ban and unperformed statement repayments."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
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
    BankStatementRow,
    BankStatementUpload,
    User,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
    InvalidReconciliationDecisionError,
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


class PendingTransferSettlementTest(CreditCardStatementBaseTest):
    """Transfers close pending statement repayments by amount and date."""

    def test_transfer_within_one_day_closes_reminder(self) -> None:
        upload = self._create_upload()
        row = self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )
        settled = self.service.settle_pending_transfers(self.card)
        self.assertEqual(settled, 0)

        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=self.card,
            amount=Decimal('199.00'),
            exchange_date=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )

        settled = self.service.settle_pending_transfers(self.card)
        self.assertEqual(settled, 1)
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertIsNotNone(row.transfer)

    def test_transfer_three_days_later_does_not_close(self) -> None:
        upload = self._create_upload()
        row = self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=self.card,
            amount=Decimal('199.00'),
            exchange_date=datetime(2026, 2, 12, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(
            self.service.settle_pending_transfers(self.card),
            0,
        )
        row.refresh_from_db()
        self.assertEqual(
            row.decision,
            BankStatementRow.Decision.NEEDS_TRANSFER,
        )

    def test_one_transfer_closes_at_most_one_row(self) -> None:
        upload = self._create_upload()
        first = self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
            position=0,
        )
        second = self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 9, 13, 0, tzinfo=UTC),
            position=1,
        )
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=self.card,
            amount=Decimal('199.00'),
            exchange_date=datetime(2026, 2, 9, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(
            self.service.settle_pending_transfers(self.card),
            1,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        closed = [
            row
            for row in (first, second)
            if row.decision == BankStatementRow.Decision.TRANSFERRED
        ]
        self.assertEqual(len(closed), 1)

    def test_two_reminders_closed_by_two_transfers(self) -> None:
        upload = self._create_upload()
        first = self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
            position=0,
        )
        second = self._create_pending_row(
            upload=upload,
            amount=Decimal('199.00'),
            when=datetime(2026, 2, 20, 12, 0, tzinfo=UTC),
            position=1,
        )
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=self.card,
            amount=Decimal('199.00'),
            exchange_date=datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
        )
        self.assertEqual(
            self.service.settle_pending_transfers(self.card),
            1,
        )
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.debit,
            to_account=self.card,
            amount=Decimal('199.00'),
            exchange_date=datetime(2026, 2, 20, 12, 0, tzinfo=UTC),
        )
        self.assertEqual(
            self.service.settle_pending_transfers(self.card),
            1,
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(
            first.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertEqual(
            second.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )
        self.assertNotEqual(first.transfer_id, second.transfer_id)


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
