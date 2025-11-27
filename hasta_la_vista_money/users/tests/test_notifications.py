from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth import get_user_model
from django.test import TestCase

from hasta_la_vista_money.users.services.notifications import (
    NotificationDict,
    get_user_notifications,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class GetUserNotificationsServiceTest(TestCase):
    """Tests for get_user_notifications service function."""

    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
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
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: User = user

    def test_get_user_notifications(self) -> None:
        notifications: list[NotificationDict] = get_user_notifications(  # type: ignore[reportArgumentType]
            self.user,
        )
        self.assertIsInstance(notifications, list)
        for note in notifications:
            self.assertIn('type', note)
            self.assertIn('title', note)
            self.assertIn('message', note)
            self.assertIn('icon', note)
