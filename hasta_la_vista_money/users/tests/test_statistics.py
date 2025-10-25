from typing import ClassVar

from django.contrib.auth import get_user_model
from django.test import TestCase

from hasta_la_vista_money.users.services.statistics import get_user_statistics

User = get_user_model()


class GetUserStatisticsServiceTest(TestCase):
    """Tests for get_user_statistics service function."""

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

    def setUp(self):
        self.user = User.objects.first()

    def test_get_user_statistics(self):
        stats = get_user_statistics(self.user)
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
