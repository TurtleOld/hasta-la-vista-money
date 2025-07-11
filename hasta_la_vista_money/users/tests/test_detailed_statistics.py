from django.test import TestCase
from django.contrib.auth import get_user_model
from hasta_la_vista_money.users.services.detailed_statistics import (
    get_user_detailed_statistics,
)

User = get_user_model()


class GetUserDetailedStatisticsServiceTest(TestCase):
    """Tests for get_user_detailed_statistics service function."""

    fixtures = [
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

    def test_get_user_detailed_statistics(self):
        stats = get_user_detailed_statistics(self.user)
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
