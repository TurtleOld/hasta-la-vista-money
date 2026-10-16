from datetime import UTC, date, datetime
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from hasta_la_vista_money.budget.models import Budget
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.services.monthly_statistics_service import (
    _budgets_data,
)

User = get_user_model()


class BudgetsDataQueriesTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='budget-user')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Main',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.food = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        self.taxi = Category.objects.create(
            user=self.user,
            name='Taxi',
            type=TransactionType.EXPENSE,
        )

    def _seed(self, months: int) -> date:
        first = date(2024, 1, 1)
        for index in range(months):
            month = first + relativedelta(months=index)
            Budget.objects.create(
                user=self.user,
                period=month,
                category=None,
                amount_limit=Decimal('1000.00'),
            )
            for category in (self.food, self.taxi):
                Budget.objects.create(
                    user=self.user,
                    period=month,
                    category=category,
                    amount_limit=Decimal('300.00'),
                )
                Transaction.objects.create(
                    user=self.user,
                    account=self.account,
                    category=category,
                    type=TransactionType.EXPENSE,
                    amount=Decimal('100.50'),
                    date=datetime(month.year, month.month, 1, 0, 0, tzinfo=UTC),
                )
            Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=self.food,
                type=TransactionType.EXPENSE,
                amount=Decimal('50.00'),
                date=datetime(month.year, month.month, 28, 23, 59, tzinfo=UTC),
            )
        return first + relativedelta(months=months - 1)

    def _count_queries(self, months: int) -> int:
        last = self._seed(months)
        with CaptureQueriesContext(connection) as ctx:
            _budgets_data([self.user], date(2024, 1, 1), last)
        return len(ctx)

    def test_actual_expenses_per_budget(self) -> None:
        last = self._seed(2)
        rows = _budgets_data([self.user], date(2024, 1, 1), last)
        self.assertEqual(len(rows), 6)
        by_key = {(r['period'], r['category_name']): r for r in rows}
        january = date(2024, 1, 1).strftime('%B %Y')
        self.assertEqual(
            by_key[(january, 'Общий лимит')]['actual_expenses'],
            251.0,
        )
        self.assertEqual(by_key[(january, 'Food')]['actual_expenses'], 150.5)
        self.assertEqual(by_key[(january, 'Taxi')]['actual_expenses'], 100.5)

    def test_query_count_does_not_grow_with_months(self) -> None:
        few = self._count_queries(3)
        Budget.objects.all().delete()
        Transaction.objects.all().delete()
        many = self._count_queries(12)
        self.assertEqual(few, many)
