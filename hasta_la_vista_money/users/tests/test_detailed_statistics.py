from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.users.services.cache import (
    get_user_detailed_statistics_cache_key,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
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

    def test_get_user_detailed_statistics_uses_cached_value(self) -> None:
        container = ApplicationContainer()
        stats_filter = StatisticsFilters()
        cache_key = get_user_detailed_statistics_cache_key(
            self.user.pk,
            stats_filter.cache_suffix,
        )
        cached_stats: UserDetailedStatisticsDict = {
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
        }
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
        base_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=StatisticsFilters(),
        )
        base_receipts = list(base_stats['receipt_page'].paginator.object_list)
        self.assertTrue(base_receipts)

        first_receipt = base_receipts[0]
        search_value = first_receipt.account.name_account
        filtered_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=StatisticsFilters(receipts_search=search_value),
        )

        filtered_receipts = list(
            filtered_stats['receipt_page'].paginator.object_list
        )
        self.assertTrue(filtered_receipts)
        for receipt in filtered_receipts:
            self.assertIn(
                search_value.lower(),
                receipt.account.name_account.lower(),
            )

    def test_operations_search_filters_income_expense(self) -> None:
        container = ApplicationContainer()
        base_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=StatisticsFilters(),
        )
        base_operations = base_stats['income_expense']
        self.assertTrue(base_operations)

        first_operation = base_operations[0]
        search_value = str(first_operation['category__name'])
        filtered_stats = get_user_detailed_statistics(
            self.user,
            container=container,
            stats_filter=StatisticsFilters(operations_search=search_value),
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
            response, 'class="statistics-panel statistics-filter-form"'
        )
        self.assertContains(response, 'hx-target="#statistics-content"')
        self.assertContains(response, 'name="operations_search"')
        self.assertContains(response, 'name="transfers_search"')
        self.assertContains(response, 'name="receipts_search"')
        self.assertContains(response, 'hx-target="#statistics-results"')


class CreditCardPaymentScheduleTest(TestCase):
    """Tests for credit card payment distribution."""

    def test_payments_after_grace_end_do_not_close_month(self) -> None:
        grace_end = timezone.make_aware(
            datetime.combine(date(2026, 8, 28), time.max),
        )
        months = [
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
        payments = [
            {
                'amount': Decimal('10000.00'),
                'date': grace_end + timedelta(days=1),
            },
        ]

        _apply_payments_to_months(months, payments)

        self.assertEqual(months[0]['payments_made'], 0.0)
        self.assertEqual(months[0]['remaining_debt'], 10000.0)
        self.assertFalse(months[0]['is_paid'])
