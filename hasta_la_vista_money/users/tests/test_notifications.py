import re
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
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

    def test_get_user_notifications(self) -> None:
        notifications: list[NotificationDict] = get_user_notifications(
            self.user,
        )
        self.assertIsInstance(notifications, list)
        for note in notifications:
            self.assertIn('type', note)
            self.assertIn('title', note)
            self.assertIn('message', note)
            self.assertIn('icon', note)

    def test_notification_icons_exist_in_icon_partial(self) -> None:
        partial = (
            Path(__file__).resolve().parents[2]
            / 'templates'
            / 'partials'
            / '_icon.html'
        ).read_text(encoding='utf-8')
        icon_names = set(re.findall(r"icon == '([a-z-]+)'", partial))
        user = User.objects.create_user(username='notification-icons')
        account = Account.objects.create(
            user=user,
            name_account='Low',
            balance=Decimal('10.00'),
        )
        now = timezone.now()
        icons_by_type: dict[str, str] = {}
        for transaction_type, amount in (
            (TransactionType.EXPENSE, Decimal('100.00')),
            (TransactionType.INCOME, Decimal('1000.00')),
        ):
            Transaction.objects.create(
                user=user,
                account=account,
                category=Category.objects.create(
                    user=user,
                    name=transaction_type,
                    type=transaction_type,
                ),
                type=transaction_type,
                amount=amount,
                date=now,
            )
            for note in get_user_notifications(user):
                icons_by_type[note['type']] = note['icon']
        self.assertEqual(
            set(icons_by_type),
            {'warning', 'danger', 'success'},
        )
        self.assertLessEqual(set(icons_by_type.values()), icon_names)
