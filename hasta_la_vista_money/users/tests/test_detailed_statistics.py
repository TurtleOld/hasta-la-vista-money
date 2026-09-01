from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.services.cache import (
    get_user_detailed_statistics_cache_key,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
    CardMonthDict,
    PaymentItemDict,
    StatisticsFilters,
    UserDetailedStatisticsDict,
    _apply_payments_to_months,
    get_user_detailed_statistics,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class GetUserDetailedStatisticsServiceTest(TestCase):
    """Tests for get_user_detailed_statistics service function."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_product.yaml',
        'receipt_seller.yaml',
        'receipt_receipt.yaml',
        'categories.yaml',
        'transactions.yaml',
    ]

    def setUp(self) -> None:
        cache.clear()
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: UserType = user

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def test_get_user_detailed_statistics(self) -> None:
        container = ApplicationContainer()
        stats_filter = StatisticsFilters()
        stats: UserDetailedStatisticsDict = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )
        self.assertIn('months_data', stats)
        self.assertIn('top_expense_categories', stats)
        self.assertIn('top_income_categories', stats)
        self.assertIn('receipt_info_by_month', stats)
        self.assertIn('income_expense', stats)
        self.assertIn('transfer_money_log', stats)
        self.assertIn('accounts', stats)
        self.assertIn('balances_by_currency', stats)
        self.assertIn('delta_by_currency', stats)
        self.assertIn('chart_combined', stats)
        self.assertIn('user', stats)
        self.assertIn('credit_cards_data', stats)
        self.assertIn('statistics_filter', stats)
        self.assertIn('statistics_members', stats)

    def test_chart_combined_keeps_shape_for_split_dynamics_charts(
        self,
    ) -> None:
        """chart_combined keeps its existing fields for the split charts.

        The dynamics tab renders a bar chart (income/expense) and a
        separate area chart (balance forecast band) from the same
        aggregate — this test pins the field shapes so the frontend
        split does not require any change to this service function.
        """
        container = ApplicationContainer()
        stats_filter = StatisticsFilters()
        stats: UserDetailedStatisticsDict = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )
        chart_combined = stats['chart_combined']
        for key in (
            'labels',
            'income_data',
            'expense_data',
            'forecast_balance',
            'forecast_lower',
            'forecast_upper',
        ):
            if key not in chart_combined:
                self.fail(f'chart_combined is missing key {key!r}')
            self.assertIsInstance(chart_combined[key], list)

    def test_get_user_detailed_statistics_uses_cached_value(self) -> None:
        container = ApplicationContainer()
        stats_filter = StatisticsFilters()
        cache_key = get_user_detailed_statistics_cache_key(
            self.user.pk,
            stats_filter.cache_suffix,
        )
        cached_stats = cast(
            'UserDetailedStatisticsDict',
            {
                'months_data': [],
                'top_expense_categories': [],
                'top_income_categories': [],
                'receipt_info_by_month': [],
                'income_expense': [],
                'transfer_money_log': [],
                'accounts': [],
                'balances_by_currency': {},
                'delta_by_currency': {},
                'chart_combined': {},
                'user': self.user,
                'credit_cards_data': [],
                'statistics_filter': stats_filter,
                'statistics_period_choices': [],
                'statistics_account_choices': [],
                'statistics_currency_choices': [],
                'statistics_category_choices': [],
                'statistics_member_choices': [],
                'statistics_members': [self.user],
            },
        )
        cache.set(cache_key, cached_stats, 600)

        stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )

        self.assertEqual(stats, cached_stats)

    def test_statistics_filters_include_server_side_search_fields(self) -> None:
        query = QueryDict(
            'operations_search=salary&transfers_search=sber'
            '&receipts_search=pyaterochka',
        )
        stats_filter = StatisticsFilters.from_query(query)

        self.assertEqual(stats_filter.operations_search, 'salary')
        self.assertEqual(stats_filter.transfers_search, 'sber')
        self.assertEqual(stats_filter.receipts_search, 'pyaterochka')
        self.assertIn('operations_search=salary', stats_filter.query_string)
        self.assertIn('transfers_search=sber', stats_filter.query_string)
        self.assertIn('receipts_search=pyaterochka', stats_filter.query_string)

    def test_receipts_search_filters_receipt_page(self) -> None:
        container = ApplicationContainer()
        base_filter = StatisticsFilters(
            period='range',
            date_from=date(2000, 1, 1),
            date_to=timezone.localdate(),
        )
        base_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=base_filter,
        )
        base_receipts = list(base_stats['receipt_page'].paginator.object_list)
        self.assertTrue(base_receipts)

        first_receipt = base_receipts[0]
        search_value = first_receipt.account.name_account
        filtered_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=StatisticsFilters(
                period='range',
                date_from=date(2000, 1, 1),
                date_to=timezone.localdate(),
                receipts_search=search_value,
            ),
        )

        filtered_receipts = list(
            filtered_stats['receipt_page'].paginator.object_list,
        )
        self.assertTrue(filtered_receipts)
        for receipt in filtered_receipts:
            self.assertIn(
                search_value.lower(),
                receipt.account.name_account.lower(),
            )

    def test_operations_search_filters_income_expense(self) -> None:
        container = ApplicationContainer()
        base_filter = StatisticsFilters(
            period='range',
            date_from=date(2000, 1, 1),
            date_to=timezone.localdate(),
        )
        base_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=base_filter,
        )
        base_operations = base_stats['income_expense']
        self.assertTrue(base_operations)

        first_operation = base_operations[0]
        search_value = str(first_operation['category__name'])
        filtered_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=StatisticsFilters(
                period='range',
                date_from=date(2000, 1, 1),
                date_to=timezone.localdate(),
                operations_search=search_value,
            ),
        )

        filtered_operations = filtered_stats['income_expense']
        self.assertTrue(filtered_operations)
        for operation in filtered_operations:
            self.assertIn(
                search_value.lower(),
                str(operation['category__name']).lower(),
            )

    def test_statistics_template_contains_htmx_server_side_controls(
        self,
    ) -> None:
        self.client.force_login(self.user)
        response = self.client.get('/users/statistics/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="statistics-content"')
        self.assertContains(response, 'id="statistics-results"')
        self.assertContains(
            response,
            'class="statistics-panel statistics-filter-form"',
        )
        self.assertContains(response, 'hx-target="#statistics-content"')
        self.assertContains(response, 'name="operations_search"')
        self.assertContains(response, 'name="transfers_search"')
        self.assertContains(response, 'name="receipts_search"')
        self.assertContains(response, 'hx-target="#statistics-results"')
        self.assertContains(response, 'id="incomeExpenseChart"')
        self.assertContains(response, 'id="balanceForecastChart"')


class CreditCardPaymentScheduleTest(TestCase):
    """Tests for credit card payment distribution."""

    def test_payments_after_grace_end_do_not_close_month(self) -> None:
        grace_end = timezone.make_aware(
            datetime.combine(date(2026, 8, 28), time.max),
        )
        months: list[CardMonthDict] = [
            {
                'month': '05.2026',
                'purchase_start': timezone.now(),
                'purchase_end': timezone.now(),
                'grace_end': grace_end,
                'debt_for_month': 10000.0,
                'is_overdue': False,
                'days_until_due': 0,
                'payments_made': 0.0,
                'remaining_debt': 0.0,
                'is_paid': False,
            },
        ]
        payments: list[PaymentItemDict] = [
            {
                'amount': Decimal('10000.00'),
                'date': grace_end + timedelta(days=1),
            },
        ]

        _apply_payments_to_months(months, payments)

        self.assertEqual(months[0]['payments_made'], 0.0)
        self.assertEqual(months[0]['remaining_debt'], 10000.0)
        self.assertFalse(months[0]['is_paid'])


class SummaryCardsAndMovingAverageTest(TestCase):
    """Tests for summary-card deltas and the expense moving average.

    Builds four consecutive months of known expense/income totals (no
    shared fixtures) so the previous-month delta and the 3-month moving
    average can be checked against hand-computed values.
    """

    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(
            username='dynamicsuser',
            password='testpass123',  # nosec B106: test-only password
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            balance=Decimal('0.00'),
            currency='RUB',
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Расходы',
            type=TransactionType.EXPENSE,
        )
        self.income_category = Category.objects.create(
            user=self.user,
            name='Доходы',
            type=TransactionType.INCOME,
        )
        self.today = timezone.now().date()

        # Known monthly totals, oldest to newest: -3, -2, -1, 0 (current).
        self.monthly_expenses = [
            Decimal('1000.00'),
            Decimal('2000.00'),
            Decimal('3000.00'),
            Decimal('4000.00'),
        ]
        self.monthly_income = Decimal('3000.00')
        for months_ago, expense_amount in zip(
            (3, 2, 1, 0),
            self.monthly_expenses,
            strict=True,
        ):
            month_date = self._month_date(months_ago)
            Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=expense_amount,
                date=month_date,
                type=TransactionType.EXPENSE,
            )
            Transaction.objects.create(
                user=self.user,
                account=self.account,
                category=self.income_category,
                amount=self.monthly_income,
                date=month_date,
                type=TransactionType.INCOME,
            )

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def _month_date(self, months_ago: int, day: int = 1) -> datetime:
        base = self.today.replace(day=1) - relativedelta(months=months_ago)
        safe_day = min(day, monthrange(base.year, base.month)[1])
        return datetime(base.year, base.month, safe_day, 12, 0, tzinfo=UTC)

    def _get_stats(self) -> UserDetailedStatisticsDict:
        container = ApplicationContainer()
        stats_filter = StatisticsFilters(period='4')
        return get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=stats_filter,
        )

    def test_summary_cards_delta_vs_previous_month(self) -> None:
        """Cards compare the last month in the period to the one before."""
        stats = self._get_stats()
        cards_by_key = {card['key']: card for card in stats['summary_cards']}

        expenses_card = cards_by_key['expenses']
        self.assertEqual(expenses_card['value'], 4000.0)
        self.assertEqual(expenses_card['delta'], 1000.0)
        if expenses_card['delta_percent'] is None:
            self.fail('expenses delta_percent should not be None')
        self.assertAlmostEqual(
            expenses_card['delta_percent'],
            1000.0 / 3000.0 * 100,
        )
        self.assertFalse(expenses_card['positive_is_good'])

        income_card = cards_by_key['income']
        self.assertEqual(income_card['value'], 3000.0)
        self.assertEqual(income_card['delta'], 0.0)
        self.assertTrue(income_card['positive_is_good'])

        savings_card = cards_by_key['savings']
        self.assertEqual(savings_card['value'], 3000.0 - 4000.0)
        self.assertEqual(savings_card['delta'], -1000.0)
        self.assertIsNone(savings_card['delta_percent'])
        self.assertTrue(savings_card['positive_is_good'])

    def test_expense_moving_average_over_three_months(self) -> None:
        """The moving average needs a full 3-month trailing window."""
        stats = self._get_stats()
        months_data = stats['months_data']
        self.assertEqual(len(months_data), 4)
        self.assertEqual(
            [month.get('expenses') for month in months_data],
            [float(amount) for amount in self.monthly_expenses],
        )

        chart_combined = stats['chart_combined']
        labels = chart_combined['labels']
        moving_average = chart_combined['expense_moving_average']
        by_date = dict(zip(labels, moving_average, strict=False))

        expected_by_months_ago = {
            3: None,
            2: None,
            1: (1000.0 + 2000.0 + 3000.0) / 3,
            0: (2000.0 + 3000.0 + 4000.0) / 3,
        }
        for months_ago, expected_value in expected_by_months_ago.items():
            transaction_date = self._month_date(months_ago).date().isoformat()
            self.assertIn(transaction_date, by_date)
            self.assertEqual(by_date[transaction_date], expected_value)
