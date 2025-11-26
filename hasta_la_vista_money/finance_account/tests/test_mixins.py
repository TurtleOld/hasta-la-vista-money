"""Tests for finance account mixins."""

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from hasta_la_vista_money.finance_account.mixins import GroupAccountMixin
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.tests.helpers import (
    setup_container_for_request,
)
from hasta_la_vista_money.users.models import User


class TestGroupAccountMixin(TestCase):
    """Test cases for GroupAccountMixin."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user1 = User.objects.create_user(
            username='user1',
            password='testpass123',
        )
        self.user2 = User.objects.create_user(
            username='user2',
            password='testpass123',
        )
        self.user3 = User.objects.create_user(
            username='user3',
            password='testpass123',
        )

        self.group = Group.objects.create(name='Test Group')
        self.user1.groups.add(self.group)
        self.user2.groups.add(self.group)

        self.account1 = Account.objects.create(
            user=self.user1,
            name_account='User1 Account',
            currency='RUB',
        )
        self.account2 = Account.objects.create(
            user=self.user2,
            name_account='User2 Account',
            currency='RUB',
        )
        self.account3 = Account.objects.create(
            user=self.user3,
            name_account='User3 Account',
            currency='RUB',
        )

        self.factory = RequestFactory()

    def test_get_accounts_user_only(self) -> None:
        """Test get_accounts method for user without groups."""
        mixin = GroupAccountMixin()
        mixin.request = self.factory.get('/')  # type: ignore[assignment]
        mixin.request.user = self.user3
        setup_container_for_request(mixin.request)

        accounts = mixin.get_accounts(self.user3)

        self.assertEqual(accounts.count(), 1)
        self.assertIn(self.account3, accounts)
        self.assertNotIn(self.account1, accounts)
        self.assertNotIn(self.account2, accounts)

    def test_get_accounts_user_with_groups(self) -> None:
        """Test get_accounts method for user with groups."""
        mixin = GroupAccountMixin()
        mixin.request = self.factory.get('/')  # type: ignore[assignment]
        mixin.request.user = self.user1
        setup_container_for_request(mixin.request)

        accounts = mixin.get_accounts(self.user1)

        self.assertEqual(accounts.count(), 2)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertNotIn(self.account3, accounts)

    def test_get_accounts_user_with_multiple_groups(self) -> None:
        """Test get_accounts method for user with multiple groups."""
        group2 = Group.objects.create(name='Test Group 2')
        self.user1.groups.add(group2)
        self.user3.groups.add(group2)

        self.account4 = Account.objects.create(
            user=self.user3,
            name_account='User3 Group2 Account',
            currency='RUB',
        )

        mixin = GroupAccountMixin()
        mixin.request = self.factory.get('/')  # type: ignore[assignment]
        mixin.request.user = self.user1
        setup_container_for_request(mixin.request)

        accounts = mixin.get_accounts(self.user1)

        self.assertEqual(accounts.count(), 4)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertIn(self.account3, accounts)
        self.assertIn(self.account4, accounts)

    def test_get_accounts_empty_groups(self) -> None:
        """Test get_accounts method for user with empty groups."""
        empty_group = Group.objects.create(name='Empty Group')
        self.user1.groups.add(empty_group)

        mixin = GroupAccountMixin()
        mixin.request = self.factory.get('/')  # type: ignore[assignment]
        mixin.request.user = self.user1
        setup_container_for_request(mixin.request)

        accounts = mixin.get_accounts(self.user1)

        self.assertEqual(accounts.count(), 2)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)

    def test_get_accounts_no_accounts(self) -> None:
        """Test get_accounts method for user with no accounts."""
        user4 = User.objects.create_user(
            username='user4',
            password='testpass123',
        )

        mixin = GroupAccountMixin()
        mixin.request = self.factory.get('/')  # type: ignore[assignment]
        mixin.request.user = user4
        setup_container_for_request(mixin.request)

        accounts = mixin.get_accounts(user4)

        self.assertEqual(accounts.count(), 0)

    def test_get_accounts_different_currencies(self) -> None:
        """Test get_accounts method with different currencies."""
        account_usd = Account.objects.create(
            user=self.user1,
            name_account='USD Account',
            currency='USD',
        )

        mixin = GroupAccountMixin()
        mixin.request = self.factory.get('/')  # type: ignore[assignment]
        mixin.request.user = self.user1
        setup_container_for_request(mixin.request)

        accounts = mixin.get_accounts(self.user1)

        self.assertEqual(accounts.count(), 3)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertIn(account_usd, accounts)

    def test_get_accounts_account_types(self) -> None:
        """Test get_accounts method with different account types."""
        credit_account = Account.objects.create(
            user=self.user1,
            name_account='Credit Account',
            currency='RUB',
            type_account='CREDIT',
        )

        mixin = GroupAccountMixin()
        mixin.request = self.factory.get('/')  # type: ignore[assignment]
        mixin.request.user = self.user1
        setup_container_for_request(mixin.request)

        accounts = mixin.get_accounts(self.user1)

        self.assertEqual(accounts.count(), 3)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertIn(credit_account, accounts)
