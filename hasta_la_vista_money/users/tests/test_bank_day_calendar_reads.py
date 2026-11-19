"""Users-side calendar reads: statistics, forecast, notifications, markup."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
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
from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.services.forecast import _monthly_net_flows
from hasta_la_vista_money.users.services.notifications import (
    get_user_notifications,
)

PAGO_PAGO = 'Pacific/Pago_Pago'


@override_settings(TIME_ZONE=PAGO_PAGO)
class UsersBankDayReadTest(TestCase):
    """Financial calendar reads use the explicit bank day."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='users-bank-day')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Карта',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )

    def _transaction(
        self,
        moment: datetime,
        bank_day: date | None,
        amount: str = '100.00',
        type_value: str = TransactionType.EXPENSE,
    ) -> Transaction:
        return Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=type_value,
            amount=Decimal(amount),
            date=moment,
            bank_calendar_date=bank_day,
        )

    def test_statistics_period_uses_the_bank_day(self) -> None:
        repository = StatisticsRepository()
        self._transaction(
            datetime(2026, 3, 1, tzinfo=UTC),
            date(2026, 3, 1),
        )
        march_start = timezone.make_aware(
            datetime.combine(date(2026, 3, 1), time.min),
        )
        march_end = timezone.make_aware(
            datetime.combine(date(2026, 3, 31), time.max),
        )
        february_start = timezone.make_aware(
            datetime.combine(date(2026, 2, 1), time.min),
        )
        february_end = timezone.make_aware(
            datetime.combine(date(2026, 2, 28), time.max),
        )

        march = repository.get_expenses_sum_by_period(
            self.user,
            'RUB',
            march_start,
            march_end,
        )
        february = repository.get_expenses_sum_by_period(
            self.user,
            'RUB',
            february_start,
            february_end,
        )

        self.assertEqual(march, Decimal('100.00'))
        self.assertEqual(february, Decimal(0))

    def test_recent_expense_order_uses_the_bank_day(self) -> None:
        bank = self._transaction(
            datetime(2026, 3, 3, tzinfo=UTC),
            date(2026, 3, 3),
            '111.00',
        )
        self._transaction(
            datetime(2026, 3, 3, 1, tzinfo=UTC),
            None,
            '222.00',
        )

        recent = StatisticsRepository().get_recent_expenses(
            self.user,
            limit=1,
        )

        self.assertEqual([item.pk for item in recent], [bank.pk])

    def test_forecast_month_keys_use_the_bank_day(self) -> None:
        self._transaction(
            datetime(2026, 3, 1, tzinfo=UTC),
            date(2026, 3, 1),
            '100.00',
            TransactionType.INCOME,
        )

        flows = _monthly_net_flows(
            [self.user],
            'RUB',
            date(2026, 2, 1),
            date(2026, 3, 31),
        )

        self.assertEqual(flows, [Decimal(0), Decimal('100.00')])

    def test_notification_month_uses_the_bank_day(self) -> None:
        month_start = timezone.localdate().replace(day=1)
        self._transaction(
            datetime.combine(month_start, time.min, tzinfo=UTC),
            month_start,
        )

        titles = [item['title'] for item in get_user_notifications(self.user)]

        self.assertIn('Превышение расходов', titles)

    def test_probable_duplicate_requires_the_same_bank_day(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/bank-day.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=datetime(2026, 3, 2, tzinfo=UTC),
            bank_calendar_date=date(2026, 3, 2),
            date_precision=BankStatementRow.DatePrecision.DAY,
            amount=Decimal('100.00'),
            description='Покупка',
            source_row_position=0,
            match_calendar_date=True,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        legacy = self._transaction(
            datetime(2026, 3, 2, 10, tzinfo=UTC),
            None,
        )
        service = ApplicationContainer().users.statement_markup_service()

        duplicates = service.probable_duplicates(upload)
        self.assertEqual(duplicates, {})

        legacy.bank_calendar_date = date(2026, 3, 2)
        legacy.save(update_fields=['bank_calendar_date'])
        duplicates = service.probable_duplicates(upload)

        self.assertIn(row.pk, duplicates)

    def test_reconciliation_candidates_use_the_bank_day(self) -> None:
        upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='bank_statements/bank-day.pdf',
            status=BankStatementUpload.Status.AWAITING_CONFIRMATION,
        )
        row = BankStatementRow.objects.create(
            upload=upload,
            transaction_type=TransactionType.EXPENSE,
            transaction_date=datetime(2026, 3, 2, tzinfo=UTC),
            bank_calendar_date=date(2026, 3, 2),
            date_precision=BankStatementRow.DatePrecision.DAY,
            amount=Decimal('100.00'),
            description='Покупка',
            source_row_position=0,
            match_calendar_date=True,
            decision=BankStatementRow.Decision.AWAITING_MARKUP,
        )
        legacy = self._transaction(
            datetime(2026, 3, 2, 10, tzinfo=UTC),
            None,
        )
        bank = self._transaction(
            datetime(2026, 3, 2, tzinfo=UTC),
            date(2026, 3, 2),
        )
        service = (
            ApplicationContainer().users.bank_statement_reconciliation_service()
        )

        candidates = service.current_candidates(row)

        self.assertEqual({item.pk for item in candidates}, {bank.pk})
        self.assertNotIn(legacy.pk, {item.pk for item in candidates})
