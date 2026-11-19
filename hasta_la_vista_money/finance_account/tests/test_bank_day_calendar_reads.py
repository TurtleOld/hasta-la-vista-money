"""Calendar reads on the finances page, credit debt and transfer matching."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from django.test import RequestFactory, TestCase, override_settings

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.views import (
    FinancesFilter,
    FinancesTransaction,
    _finances_transactions,
    _recent_transactions,
)
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.repositories.transfer_matching import (
    find_mirroring_transfers,
)

PAGO_PAGO = 'Pacific/Pago_Pago'


@override_settings(TIME_ZONE=PAGO_PAGO)
class BankDayReadTest(TestCase):
    """A UTC midnight anchor never loses its bank day in calendar reads."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username='bank-day-reads')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Карта',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.other = Account.objects.create(
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

    def _transaction(
        self,
        moment: datetime,
        bank_day: date | None,
        amount: str = '100.00',
    ) -> Transaction:
        return Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal(amount),
            date=moment,
            bank_calendar_date=bank_day,
        )

    def _finances(self, **kwargs: Any) -> list[FinancesTransaction]:
        request = RequestFactory().get('/finances')
        request.user = self.user
        return _finances_transactions(
            request=request,
            users=[self.user],
            finances_filter=FinancesFilter(period='all', **kwargs),
        )

    def test_finances_day_filter_uses_the_bank_day(self) -> None:
        moment = datetime(2026, 3, 2, tzinfo=UTC)
        bank = self._transaction(moment, date(2026, 3, 2))
        legacy = self._transaction(moment, None)

        on_bank_day = self._finances(
            date_from=date(2026, 3, 2),
            date_to=date(2026, 3, 2),
        )

        self.assertEqual([row.source_id for row in on_bank_day], [bank.pk])
        self.assertNotIn(legacy.pk, [row.source_id for row in on_bank_day])

    def test_finances_latest_order_uses_the_bank_day(self) -> None:
        bank = self._transaction(
            datetime(2026, 3, 3, tzinfo=UTC),
            date(2026, 3, 3),
            '111.00',
        )
        later_moment = self._transaction(
            datetime(2026, 3, 3, 1, tzinfo=UTC),
            None,
            '222.00',
        )

        rows = self._finances()

        self.assertIsNone(later_moment.bank_calendar_date)
        self.assertEqual(
            [row.source_id for row in rows],
            [bank.pk, later_moment.pk],
        )

    def test_recent_movements_order_uses_the_bank_day(self) -> None:
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

        days = _recent_transactions(self.user, [self.user], limit=1)

        self.assertEqual(days[0].date, date(2026, 3, 3))
        self.assertEqual(days[0].items[0].source_id, bank.pk)

    def test_credit_card_debt_period_uses_the_bank_day(self) -> None:
        credit = Account.objects.create(
            user=self.user,
            name_account='Кредитка',
            balance=Decimal('0.00'),
            currency='RUB',
            type_account='CreditCard',
        )
        Transaction.objects.create(
            user=self.user,
            account=credit,
            category=self.category,
            type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            date=datetime(2026, 3, 1, tzinfo=UTC),
            bank_calendar_date=date(2026, 3, 1),
        )
        service = ApplicationContainer().finance_account.account_service()

        march = service.get_credit_card_debt(
            credit,
            date(2026, 3, 1),
            date(2026, 3, 31),
        )
        february = service.get_credit_card_debt(
            credit,
            date(2026, 2, 1),
            date(2026, 2, 28),
        )

        self.assertEqual(march, Decimal('100.00'))
        self.assertEqual(february, Decimal(0))

    def test_transfer_matching_uses_the_bank_day(self) -> None:
        transfer = TransferMoneyLog.objects.create(
            user=self.user,
            from_account=self.account,
            to_account=self.other,
            amount=Decimal('100.00'),
            exchange_date=datetime(2026, 3, 1, tzinfo=UTC),
            bank_calendar_date=date(2026, 3, 1),
        )

        matches = find_mirroring_transfers(
            account=self.account,
            user=self.user,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal('100.00'),
            row_date=date(2026, 3, 2),
        )

        self.assertEqual(list(matches), [transfer])
