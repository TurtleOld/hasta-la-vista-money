"""Public rendering of an explicit bank calendar day.

A movement with ``bank_calendar_date`` displays and groups by that day
regardless of the active timezone and never shows clock hours. A legacy
movement without the field keeps its moment and its local day.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

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
