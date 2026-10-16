from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.models import Budget
from hasta_la_vista_money.constants import ACCOUNT_TYPE_CREDIT_CARD
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.services.category_statistics_service import (
    _category_drilldown_transactions,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
    StatisticsFilters,
)
from hasta_la_vista_money.users.services.monthly_statistics_service import (
    _budgets_data,
)
from hasta_la_vista_money.users.services.summary_statistics_service import (
    _build_single_card_month,
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


class RaiffeisenScheduleCallsTest(TestCase):
    def test_schedule_is_calculated_once_per_card_month(self) -> None:
        user = User.objects.create_user(username='raiff-user')
        card = Account.objects.create(
            user=user,
            name_account='Raiffeisen',
            balance=Decimal('0.00'),
            limit_credit=Decimal('100000.00'),
            currency='RUB',
            type_account=ACCOUNT_TYPE_CREDIT_CARD,
            bank=Bank.objects.get(code='RAIFFAISENBANK'),
        )
        month = date(2026, 3, 1)
        grace_end = datetime(2026, 5, 20, tzinfo=UTC)
        account_service = mock.Mock()
        schedule_mock = (
            account_service.calculate_raiffeisenbank_payment_schedule
        )
        schedule_mock.return_value = {
            'grace_end_date': grace_end,
            'final_debt': Decimal('90.00'),
        }

        month_data, final_debt = _build_single_card_month(
            month,
            {month: Decimal('100.00')},
            defaultdict(lambda: defaultdict(Decimal)),
            card,
            account_service,
            datetime(2026, 4, 1, tzinfo=UTC),
        )

        self.assertEqual(schedule_mock.call_count, 1)
        self.assertEqual(month_data['grace_end'], grace_end)
        self.assertEqual(final_debt, Decimal('90.00'))


class CategoryDrilldownTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='drill-user')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Main',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.parent = self._category('Parent')
        self.child = Category.objects.create(
            user=self.user,
            name='Child',
            type=TransactionType.EXPENSE,
            parent_category=self.parent,
        )
        self.other = self._category('Other')

    def _category(self, name: str) -> Category:
        return Category.objects.create(
            user=self.user,
            name=name,
            type=TransactionType.EXPENSE,
        )

    def _expense(self, category: Category, day: int, amount: str) -> None:
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=category,
            type=TransactionType.EXPENSE,
            amount=Decimal(amount),
            date=datetime(2026, 1, day, 12, 0, tzinfo=UTC),
        )

    def _drilldown(self, ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        return _category_drilldown_transactions(
            TransactionType.EXPENSE,
            [self.user],
            StatisticsFilters(),
            date(2026, 1, 1),
            date(2026, 1, 31),
            ids,
        )

    def test_children_are_included_and_limited_to_page_size(self) -> None:
        for day in range(1, 9):
            self._expense(self.parent, day, '10.00')
        for day in range(9, 14):
            self._expense(self.child, day, '5.00')
        self._expense(self.other, 20, '1.00')

        result = self._drilldown([self.parent.pk, self.other.pk])

        parent_rows = result[self.parent.pk]
        self.assertEqual(len(parent_rows), constants.PAGINATE_BY_DEFAULT)
        self.assertEqual(
            [row['date'].day for row in parent_rows],
            list(range(13, 3, -1)),
        )
        self.assertEqual(parent_rows[0]['category__name'], 'Child')
        self.assertEqual(len(result[self.other.pk]), 1)

    def test_child_listed_next_to_its_parent_keeps_own_rows(self) -> None:
        for day in range(1, 13):
            self._expense(self.parent, day, '10.00')
        self._expense(self.child, 1, '5.00')

        result = self._drilldown([self.parent.pk, self.child.pk])

        self.assertEqual(len(result[self.parent.pk]), 10)
        self.assertEqual(len(result[self.child.pk]), 1)

    def test_query_count_does_not_grow_with_categories(self) -> None:
        self._expense(self.parent, 1, '10.00')
        with CaptureQueriesContext(connection) as single:
            self._drilldown([self.parent.pk])
        extra = [self._category(f'Extra {i}') for i in range(5)]
        for category in extra:
            self._expense(category, 2, '1.00')
        ids = [self.parent.pk, *(category.pk for category in extra)]
        with CaptureQueriesContext(connection) as many:
            self._drilldown(ids)
        self.assertEqual(len(single), len(many))
