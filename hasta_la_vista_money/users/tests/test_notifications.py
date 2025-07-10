from django.test import TestCase
from django.contrib.auth import get_user_model
from hasta_la_vista_money.users.services.notifications import get_user_notifications

User = get_user_model()


class GetUserNotificationsServiceTest(TestCase):
    """Tests for get_user_notifications service function."""

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

    def test_get_user_notifications(self):
        notifications = get_user_notifications(self.user)
        self.assertIsInstance(notifications, list)
        for note in notifications:
            self.assertIn('type', note)
            self.assertIn('title', note)
            self.assertIn('message', note)
            self.assertIn('icon', note)
