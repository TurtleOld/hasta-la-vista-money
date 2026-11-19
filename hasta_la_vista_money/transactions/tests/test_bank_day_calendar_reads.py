"""Transaction API calendar filters keep the explicit bank day."""

from datetime import UTC, date, datetime
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User

PAGO_PAGO = 'Pacific/Pago_Pago'


@override_settings(TIME_ZONE=PAGO_PAGO)
class BankDayAPITest(TestCase):
    """Anchored movements stay on their bank day in API filters."""

    fixtures = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
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
        amount: str,
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

    def test_data_inclusive_filter_uses_the_bank_day(self) -> None:
        bank = self._transaction(
            datetime(2026, 3, 2, tzinfo=UTC),
            date(2026, 3, 2),
            '111.00',
        )
        self._transaction(
            datetime(2026, 3, 2, tzinfo=UTC),
            None,
            '222.00',
        )

        response = self.client.get(
            reverse('api:transactions:data')
            + '?date_after=2026-03-02&date_before=2026-03-02',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row['id'] for row in response.json()['results']],
            [bank.pk],
        )

    def test_by_group_orders_by_the_bank_day(self) -> None:
        bank = self._transaction(
            datetime(2026, 3, 3, tzinfo=UTC),
            date(2026, 3, 3),
            '111.00',
        )
        legacy = self._transaction(
            datetime(2026, 3, 3, 1, tzinfo=UTC),
            None,
            '222.00',
        )

        response = self.client.get(reverse('api:transactions:by_group'))

        self.assertEqual(
            [row['id'] for row in response.json()['results']],
            [bank.pk, legacy.pk],
        )
