from django.test import TestCase
from django.contrib.auth import get_user_model
from hasta_la_vista_money.users.services.export import get_user_export_data

User = get_user_model()


class GetUserExportDataServiceTest(TestCase):
    """Tests for get_user_export_data service function."""

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

    def test_get_user_export_data(self):
        data = get_user_export_data(self.user)
        self.assertIn('user_info', data)
        self.assertIn('accounts', data)
        self.assertIn('expenses', data)
        self.assertIn('incomes', data)
        self.assertIn('receipts', data)
        self.assertIn('statistics', data)
        self.assertEqual(data['user_info']['username'], self.user.username)
        self.assertIsInstance(data['accounts'], list)
        self.assertIsInstance(data['expenses'], list)
        self.assertIsInstance(data['incomes'], list)
        self.assertIsInstance(data['receipts'], list)
        self.assertIsInstance(data['statistics'], dict)
