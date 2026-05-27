from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.cache import cache
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
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: UserType = user

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
