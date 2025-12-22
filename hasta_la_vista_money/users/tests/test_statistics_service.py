"""Тесты для UserStatisticsService."""

from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth import get_user_model
from django.test import TestCase

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
    """Тесты для UserStatisticsService."""

    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
        'expense_cat.yaml',
        'expense.yaml',
        'income_cat.yaml',
        'income.yaml',
        'receipt_product.yaml',
        'receipt_seller.yaml',
        'receipt_receipt.yaml',
    ]

    def setUp(self) -> None:
        """Настройка тестового окружения."""
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
        """Тест получения статистики пользователя."""
        stats: UserStatistics = self.service.get_user_statistics(self.user)

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
        """Тест инвалидации кеша статистики."""
        self.service.get_user_statistics(self.user)
        self.service.invalidate_cache(self.user)
