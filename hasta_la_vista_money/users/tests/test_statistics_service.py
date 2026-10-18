"""Tests for UserStatisticsService.

This module provides test cases for UserStatisticsService including
statistics retrieval and cache invalidation.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.factories import AccountFactory
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.services.statistics import (
    UserStatistics,
    UserStatisticsService,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class UserStatisticsServiceTest(TestCase):
    """Test cases for UserStatisticsService.

    Tests user statistics retrieval, caching, and data structure validation.
    """

    fixtures: list[str] = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_product.yaml',
        'receipt_seller.yaml',
        'receipt_receipt.yaml',
        'categories.yaml',
        'transactions.yaml',
    ]

    def setUp(self) -> None:
        """Set up test environment."""
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: UserType = user
        self.repository = StatisticsRepository()
        self.service = UserStatisticsService(
            statistics_repository=self.repository,
        )

    def test_get_user_statistics(self) -> None:
        """Test user statistics retrieval."""
        stats: UserStatistics = self.service.get_user_statistics(
            self.user,
            'RUB',
        )

        self.assertIn('total_balance', stats)
        self.assertIn('accounts_count', stats)
        self.assertIn('current_month_expenses', stats)
        self.assertIn('current_month_income', stats)
        self.assertIn('last_month_expenses', stats)
        self.assertIn('last_month_income', stats)
        self.assertIn('recent_expenses', stats)
        self.assertIn('recent_incomes', stats)
        self.assertIn('receipts_count', stats)
        self.assertIn('top_expense_categories', stats)
        self.assertIn('monthly_savings', stats)
        self.assertIn('last_month_savings', stats)

    def test_invalidate_cache(self) -> None:
        """Test statistics cache invalidation."""
        self.service.get_user_statistics(self.user, 'RUB')
        self.service.invalidate_cache(self.user, 'RUB')


class UserStatisticsCurrencyTest(TestCase):
    """Profile statistics never mix currencies in one figure."""

    def setUp(self) -> None:
        cache.clear()
        self.user = User.objects.create_user(username='profile-currency')
        category = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        for currency, balance, spent in (
            ('RUB', '100.00', '300.00'),
            ('USD', '5.00', '7.00'),
        ):
            account = AccountFactory(
                user=self.user,
                currency=currency,
                balance=Decimal(balance),
            )
            Transaction.objects.create(
                user=self.user,
                account=account,
                category=category,
                type=TransactionType.EXPENSE,
                amount=Decimal(spent),
                date=timezone.now(),
            )

    def test_sums_only_requested_currency(self) -> None:
        service = ApplicationContainer().users.user_statistics_service()

        rub = service.get_user_statistics(self.user, 'RUB')
        usd = service.get_user_statistics(self.user, 'USD')

        self.assertEqual(rub['total_balance'], Decimal('100.00'))
        self.assertEqual(rub['accounts_count'], 1)
        self.assertEqual(rub['current_month_expenses'], Decimal('300.00'))
        self.assertEqual(
            [row['total'] for row in rub['top_expense_categories']],
            [Decimal('300.00')],
        )
        self.assertEqual(usd['total_balance'], Decimal('5.00'))
        self.assertEqual(usd['current_month_expenses'], Decimal('7.00'))

    def test_profile_uses_analytics_currency(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('users:profile', args=[self.user.pk]) + '?currency=USD',
        )

        stats = response.context['user_statistics']
        self.assertEqual(stats['total_balance'], Decimal('5.00'))
        self.assertEqual(stats['current_month_expenses'], Decimal('7.00'))
