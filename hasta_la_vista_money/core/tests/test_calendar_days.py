"""Calendar-day reads keep an explicit bank day and legacy local days."""

from datetime import UTC, date, datetime
from decimal import Decimal

from django.db.models import Sum
from django.test import TestCase, override_settings

from hasta_la_vista_money.core.calendar_days import (
    calendar_day,
    calendar_month,
    filter_calendar_range,
    movement_calendar_date,
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
from hasta_la_vista_money.users.models import User

PAGO_PAGO = 'Pacific/Pago_Pago'
KIRITIMATI = 'Pacific/Kiritimati'


class CalendarDayReadTest(TestCase):
    """The shared expression and python selector agree with the bank day."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='calendar-read')
        self.category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        self.account = self._account('Карта')
        self.other = self._account('Копилка')

    def _account(self, name: str) -> Account:
        return Account.objects.create(
            user=self.user,
            name_account=name,
            balance=Decimal('0.00'),
            currency='RUB',
        )

    def _transaction(
        self,
        moment: datetime,
        bank_day: date | None,
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

    @override_settings(TIME_ZONE=PAGO_PAGO)
    def test_bank_day_wins_in_a_negative_timezone(self) -> None:
        transaction = self._transaction(
            datetime(2026, 3, 2, tzinfo=UTC),
            date(2026, 3, 2),
        )

        on_bank_day = filter_calendar_range(
            Transaction.objects.filter(pk=transaction.pk),
            date(2026, 3, 2),
            date(2026, 3, 2),
        )
        on_local_day = filter_calendar_range(
            Transaction.objects.filter(pk=transaction.pk),
            date(2026, 3, 1),
            date(2026, 3, 1),
        )

        self.assertEqual(list(on_bank_day), [transaction])
        self.assertFalse(on_local_day.exists())
        self.assertEqual(
            movement_calendar_date(transaction.date, date(2026, 3, 2)),
            date(2026, 3, 2),
        )
        self.assertEqual(
            list(
                Transaction.objects.annotate(day=calendar_day()).values_list(
                    'day',
                    flat=True,
                ),
            ),
            [date(2026, 3, 2)],
        )

    @override_settings(TIME_ZONE=PAGO_PAGO)
    def test_legacy_row_keeps_its_local_day(self) -> None:
        legacy = self._transaction(datetime(2026, 3, 2, tzinfo=UTC), None)

        local_day = filter_calendar_range(
            Transaction.objects.filter(pk=legacy.pk),
            date(2026, 3, 1),
            date(2026, 3, 1),
        )
        bank_shape = filter_calendar_range(
            Transaction.objects.filter(pk=legacy.pk),
            date(2026, 3, 2),
            date(2026, 3, 2),
        )

        self.assertEqual(list(local_day), [legacy])
        self.assertFalse(bank_shape.exists())
        self.assertEqual(
            movement_calendar_date(legacy.date, None),
            date(2026, 3, 1),
        )

    @override_settings(TIME_ZONE=KIRITIMATI)
    def test_datetime_moment_is_not_claimed_as_a_bank_day(self) -> None:
        moment = datetime(2026, 3, 1, 23, 0, tzinfo=UTC)
        legacy = self._transaction(moment, None)

        local_day = filter_calendar_range(
            Transaction.objects.filter(pk=legacy.pk),
            date(2026, 3, 2),
            date(2026, 3, 2),
        )

        self.assertEqual(list(local_day), [legacy])
        self.assertIsNone(legacy.bank_calendar_date)

    @override_settings(TIME_ZONE=PAGO_PAGO)
    def test_year_boundary_uses_the_bank_year(self) -> None:
        transaction = self._transaction(
            datetime(2026, 1, 1, tzinfo=UTC),
            date(2026, 1, 1),
        )

        in_year = filter_calendar_range(
            Transaction.objects.filter(pk=transaction.pk),
            date(2026, 1, 1),
            date(2026, 12, 31),
        )
        previous_year = filter_calendar_range(
            Transaction.objects.filter(pk=transaction.pk),
            date(2025, 1, 1),
            date(2025, 12, 31),
        )

        self.assertEqual(list(in_year), [transaction])
        self.assertFalse(previous_year.exists())

    @override_settings(TIME_ZONE=PAGO_PAGO)
    def test_month_keys_keep_datetime_type_and_bank_month(self) -> None:
        self._transaction(
            datetime(2026, 1, 1, tzinfo=UTC),
            date(2026, 1, 1),
        )
        legacy = self._transaction(datetime(2026, 1, 1, tzinfo=UTC), None)

        grouped = {
            row['month'].date(): row['total']
            for row in Transaction.objects.annotate(
                month=calendar_month(),
            )
            .values('month')
            .annotate(total=Sum('amount'))
        }

        self.assertEqual(grouped[date(2026, 1, 1)], Decimal('100.00'))
        self.assertEqual(grouped[date(2025, 12, 1)], Decimal('100.00'))
        self.assertIsNone(legacy.bank_calendar_date)

    @override_settings(TIME_ZONE=PAGO_PAGO)
    def test_transfer_reads_share_the_contract(self) -> None:
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other,
            amount=Decimal('50.00'),
            exchange_date=datetime(2026, 3, 2, tzinfo=UTC),
            bank_calendar_date=date(2026, 3, 2),
        )

        found = filter_calendar_range(
            TransferMoneyLog.objects.filter(pk=transfer.pk),
            date(2026, 3, 2),
            date(2026, 3, 2),
            field='exchange_date',
        )

        self.assertEqual(list(found), [transfer])
