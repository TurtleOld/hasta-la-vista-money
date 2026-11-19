"""Public rendering of an explicit bank calendar day.

A movement with ``bank_calendar_date`` displays and groups by that day
regardless of the active timezone and never shows clock hours. A legacy
movement without the field keeps its moment and its local day.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
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
from hasta_la_vista_money.users.tests.statement_identity_fixtures import (
    statement_identity_settings,
)

PAGO_PAGO = 'Pacific/Pago_Pago'
KIRITIMATI = 'Pacific/Kiritimati'


class BankDayDisplayTestCase(TestCase):
    """Shared accounts for bank day display tests."""

    viewer_timezone: str | None = None

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='bank-day',
            password='test-only-secret',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Карта',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.other_account = Account.objects.create(
            user=self.user,
            name_account='Копилка',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        if self.viewer_timezone is not None:
            self.user.timezone_name = self.viewer_timezone
            self.user.save(update_fields=['timezone_name'])
        self.client.force_login(self.user)

    def create_transaction(
        self,
        moment: datetime,
        bank_day: date | None = None,
    ) -> Transaction:
        return Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=moment,
            bank_calendar_date=bank_day,
        )


class TestAccountLastOperationsBankDay(BankDayDisplayTestCase):
    """The dashboard widget groups and displays the explicit bank day."""

    viewer_timezone = PAGO_PAGO

    def test_transaction_bank_day_has_no_clock_hours(self) -> None:
        self.create_transaction(
            datetime(2026, 3, 15, tzinfo=UTC),
            date(2026, 3, 15),
        )

        response = self.client.get(reverse('finance_account:list'))

        days = response.context['last_operations']
        self.assertEqual([day.date for day in days], [date(2026, 3, 15)])
        self.assertContains(response, '15.03.2026')
        self.assertNotContains(response, '13:00')
        self.assertNotContains(response, '00:00')

    def test_transfer_bank_day_has_no_clock_hours(self) -> None:
        TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other_account,
            amount=Decimal('50.00'),
            exchange_date=datetime(2026, 3, 15, tzinfo=UTC),
            bank_calendar_date=date(2026, 3, 15),
        )

        response = self.client.get(reverse('finance_account:list'))

        days = response.context['last_operations']
        self.assertEqual([day.date for day in days], [date(2026, 3, 15)])
        self.assertContains(response, '15.03.2026')
        self.assertNotContains(response, '13:00')
        self.assertNotContains(response, '00:00')


class TestAccountLastOperationsLegacyMoment(BankDayDisplayTestCase):
    """A movement without a bank day keeps its local day and clock."""

    viewer_timezone = KIRITIMATI

    def test_legacy_transaction_keeps_moment(self) -> None:
        self.create_transaction(datetime(2026, 3, 15, 22, tzinfo=UTC))

        response = self.client.get(reverse('finance_account:list'))

        days = response.context['last_operations']
        self.assertEqual([day.date for day in days], [date(2026, 3, 16)])
        self.assertContains(response, '16.03.2026')
        self.assertContains(response, '12:00')


class TestFinancesBankDay(BankDayDisplayTestCase):
    """The combined finances page shows the standalone bank day."""

    viewer_timezone = PAGO_PAGO

    def test_row_shows_bank_day_not_local_moment(self) -> None:
        self.create_transaction(
            datetime(2026, 3, 15, tzinfo=UTC),
            date(2026, 3, 15),
        )

        response = self.client.get(
            reverse('finances'),
            {'period': 'all'},
        )

        self.assertContains(response, '15.03.2026')
        self.assertNotContains(response, '14.03.2026')


@statement_identity_settings
class TestReconciliationBankDay(BankDayDisplayTestCase):
    """Statement rows and candidates show their explicit bank day."""

    viewer_timezone = PAGO_PAGO

    def setUp(self) -> None:
        super().setUp()
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/bank-day-display.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )

    def create_row(
        self,
        matter: datetime,
        bank_day: date,
        *,
        position: int,
    ) -> BankStatementRow:
        return BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=matter,
            bank_calendar_date=bank_day,
            date_precision=BankStatementRow.DatePrecision.DAY,
            amount=Decimal('100.00'),
            description='Покупка',
            source_ref=f'bank-day-{position}',
            source_ref_hash=str(position) * 64,
            source_row_position=position,
        )

    def test_row_and_transaction_candidate_show_bank_day(self) -> None:
        row = self.create_row(
            datetime(2026, 3, 15, tzinfo=UTC),
            date(2026, 3, 15),
            position=0,
        )
        candidate = self.create_transaction(
            datetime(2026, 3, 15, tzinfo=UTC),
            date(2026, 3, 15),
        )
        BankStatementCandidate.objects.create(
            row=row,
            transaction=candidate,
            description='Покупка',
            rank=0,
        )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '15.03.2026')
        self.assertNotContains(response, '14.03.2026')
        self.assertNotContains(response, '00:00')

    def test_transfer_candidate_shows_bank_day(self) -> None:
        row = self.create_row(
            datetime(2026, 3, 15, tzinfo=UTC),
            date(2026, 3, 15),
            position=0,
        )
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other_account,
            amount=Decimal('100.00'),
            exchange_date=datetime(2026, 3, 15, tzinfo=UTC),
            bank_calendar_date=date(2026, 3, 15),
        )
        BankStatementCandidate.objects.create(
            row=row,
            transfer=transfer,
            description='Перевод',
            rank=0,
        )

        response = self.client.get(
            reverse(
                'finance_account:bank_statement_reconciliation',
                args=[self.upload.pk],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '15.03.2026')
        self.assertNotContains(response, '14.03.2026')
        self.assertNotContains(response, '00:00')


class TestTransactionEditBankDay(BankDayDisplayTestCase):
    """Editing a movement with a known bank day keeps day precision."""

    viewer_timezone = PAGO_PAGO

    def setUp(self) -> None:
        super().setUp()
        self.other_category = Category.objects.create(
            user=self.user,
            name='Транспорт',
            type=TransactionType.EXPENSE,
        )
        self.transaction = self.create_transaction(
            datetime(2026, 3, 15, tzinfo=UTC),
            date(2026, 3, 15),
        )
        self.account.balance = Decimal('1000.00')
        self.account.save(update_fields=['balance'])

    def _edit_url(self) -> str:
        return reverse(
            'finance_account:transaction_change',
            args=[self.transaction.pk],
        )

    def _post(
        self,
        day: str,
        category: Category | None = None,
        *,
        type_value: str = TransactionType.EXPENSE,
    ) -> Any:
        selected = category or self.category
        return self.client.post(
            self._edit_url(),
            {
                'type': type_value,
                'category': selected.pk,
                'account': self.account.pk,
                'date': day,
                'amount': '100.00',
            },
        )

    def test_edit_form_renders_date_only_initial_bank_day(self) -> None:
        response = self.client.get(self._edit_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="date"')
        self.assertContains(response, 'value="2026-03-15"')
        self.assertNotContains(response, 'type="datetime-local"')
        self.assertNotContains(response, '2026-03-14')

    def test_unchanged_date_with_category_edit_keeps_day_precision(
        self,
    ) -> None:
        response = self._post('2026-03-15', self.other_category)

        self.assertRedirects(
            response,
            reverse('finances'),
            fetch_redirect_response=False,
        )
        self.transaction.refresh_from_db()
        self.assertEqual(
            self.transaction.bank_calendar_date,
            date(2026, 3, 15),
        )
        self.assertEqual(
            self.transaction.date,
            datetime(2026, 3, 15, tzinfo=UTC),
        )
        self.assertTrue(
            AuditLog.objects.filter(
                model_name='transactions.Transaction',
                object_pk=str(self.transaction.pk),
                action=AuditLog.Action.UPDATE,
                kind=AuditOperationKind.TRANSACTION_EDIT,
            ).exists(),
        )

    def test_changed_bank_day_updates_metadata_coherently(self) -> None:
        response = self._post('2026-03-16')

        self.assertRedirects(
            response,
            reverse('finances'),
            fetch_redirect_response=False,
        )
        self.transaction.refresh_from_db()
        self.assertEqual(
            self.transaction.bank_calendar_date,
            date(2026, 3, 16),
        )
        self.assertEqual(
            self.transaction.date,
            datetime(2026, 3, 16, tzinfo=UTC),
        )
        self.assertTrue(
            AuditLog.objects.filter(
                model_name='transactions.Transaction',
                object_pk=str(self.transaction.pk),
                action=AuditLog.Action.UPDATE,
                kind=AuditOperationKind.TRANSACTION_EDIT,
            ).exists(),
        )


class TestTransactionEditLegacyMoment(BankDayDisplayTestCase):
    """A manual movement without a bank day keeps its datetime and moment."""

    viewer_timezone = KIRITIMATI

    def test_edit_form_and_post_keep_legacy_moment(self) -> None:
        moment = datetime(2026, 3, 15, 22, tzinfo=UTC)
        transaction = self.create_transaction(moment)

        response = self.client.get(
            reverse(
                'finance_account:transaction_change',
                args=[transaction.pk],
            ),
        )

        self.assertContains(response, 'type="datetime-local"')
        self.assertContains(response, 'value="2026-03-16T12:00"')
        self.assertNotContains(response, 'type="date"')

        response = self.client.post(
            reverse(
                'finance_account:transaction_change',
                args=[transaction.pk],
            ),
            {
                'type': TransactionType.EXPENSE,
                'category': self.category.pk,
                'account': self.account.pk,
                'date': '2026-03-16T12:00',
                'amount': '100.00',
            },
        )

        self.assertRedirects(
            response,
            reverse('finances'),
            fetch_redirect_response=False,
        )
        transaction.refresh_from_db()
        self.assertIsNone(transaction.bank_calendar_date)
        self.assertEqual(transaction.date, moment)


class TestPendingRepaymentBankDay(BankDayDisplayTestCase):
    """Repayment link and transfer form carry the explicit bank day."""

    viewer_timezone = PAGO_PAGO

    def setUp(self) -> None:
        super().setUp()
        self.card = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            type_account=constants.ACCOUNT_TYPE_CREDIT_CARD,
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.card,
            pdf_file='bank_statements/bank-day-repayment.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        self.row = BankStatementRow.objects.create(
            upload=self.upload,
            transaction_type=BankStatementRow.TransactionType.INCOME,
            transaction_date=datetime(2026, 3, 15, tzinfo=UTC),
            bank_calendar_date=date(2026, 3, 15),
            date_precision=BankStatementRow.DatePrecision.DAY,
            amount=Decimal('100.00'),
            description='Погашение',
            decision=BankStatementRow.Decision.NEEDS_TRANSFER,
            source_row_position=0,
        )
        self.account.balance = Decimal('1000.00')
        self.account.save(update_fields=['balance'])

    def _transfer_url(self) -> str:
        return reverse('finance_account:transfer_money')

    def test_pending_link_uses_bank_day_instead_of_local_moment(self) -> None:
        response = self.client.get(reverse('finance_account:list'))

        self.assertContains(
            response,
            f'date=2026-03-15&statement_row={self.row.pk}',
        )
        self.assertNotContains(
            response,
            f'date=2026-03-14&statement_row={self.row.pk}',
        )

    def test_transfer_form_uses_owned_bank_day_not_query_date(self) -> None:
        params: dict[str, str | int] = {
            'to_account': self.card.pk,
            'statement_row': self.row.pk,
            'date': '2026-03-14',
        }
        response = self.client.get(self._transfer_url(), params)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="date"')
        self.assertContains(response, 'value="2026-03-15"')
        self.assertNotContains(response, 'type="datetime-local"')
        self.assertNotContains(response, 'value="2026-03-14"')

    def test_transfer_post_keeps_bank_day_precision(self) -> None:
        response = self.client.post(
            self._transfer_url(),
            {
                'from_account': self.account.pk,
                'to_account': self.card.pk,
                'amount': '100.00',
                'exchange_date': '2026-03-15',
                'notes': '',
                'statement_row': self.row.pk,
            },
        )

        self.assertRedirects(
            response,
            reverse('finance_account:list'),
            fetch_redirect_response=False,
        )
        transfer = TransferMoneyLog.objects.get()
        self.assertEqual(
            transfer.bank_calendar_date,
            date(2026, 3, 15),
        )
        self.assertEqual(
            transfer.exchange_date,
            datetime(2026, 3, 15, tzinfo=UTC),
        )
        self.row.refresh_from_db()
        self.assertEqual(
            self.row.decision,
            BankStatementRow.Decision.TRANSFERRED,
        )

    def test_expired_row_does_not_supply_bank_day_to_form(self) -> None:
        BankStatementUpload.objects.filter(pk=self.upload.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        params: dict[str, str | int] = {
            'to_account': self.card.pk,
            'statement_row': self.row.pk,
            'date': '2026-03-14',
        }
        response = self.client.get(self._transfer_url(), params)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="datetime-local"')
        self.assertNotContains(response, 'value="2026-03-15"')
        self.assertNotContains(response, 'value="2026-03-14"')
