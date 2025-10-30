"""Tests for finance account services."""

from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase

from hasta_la_vista_money.finance_account import services as account_services
from hasta_la_vista_money.finance_account.models import Account, TransferMoneyLog
from hasta_la_vista_money.users.models import User


class TestAccountServices(TestCase):
    """Test cases for account service functions."""

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

        self.account1 = Account.objects.create(
            user=self.user1,
            name_account='User1 Account 1',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.account2 = Account.objects.create(
            user=self.user1,
            name_account='User1 Account 2',
            balance=Decimal('500.00'),
            currency='RUB',
        )
        self.account3 = Account.objects.create(
            user=self.user2,
            name_account='User2 Account',
            balance=Decimal('2000.00'),
            currency='RUB',
        )

    def test_get_accounts_for_user_or_group_none(self) -> None:
        """Test get_accounts_for_user_or_group with None group_id."""
        accounts = account_services.get_accounts_for_user_or_group(
            self.user1,
            None,
        )
        
        self.assertEqual(accounts.count(), 2)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertNotIn(self.account3, accounts)

    def test_get_accounts_for_user_or_group_my(self) -> None:
        """Test get_accounts_for_user_or_group with 'my' group_id."""
        accounts = account_services.get_accounts_for_user_or_group(
            self.user1,
            'my',
        )
        
        self.assertEqual(accounts.count(), 2)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertNotIn(self.account3, accounts)

    def test_get_accounts_for_user_or_group_with_group(self) -> None:
        """Test get_accounts_for_user_or_group with group."""
        group = Group.objects.create(name='Test Group')
        self.user1.groups.add(group)
        self.user2.groups.add(group)

        accounts = account_services.get_accounts_for_user_or_group(
            self.user1,
            str(group.pk),
        )
        
        self.assertEqual(accounts.count(), 3)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertIn(self.account3, accounts)

    def test_get_accounts_for_user_or_group_invalid_group(self) -> None:
        """Test get_accounts_for_user_or_group with invalid group_id."""
        accounts = account_services.get_accounts_for_user_or_group(
            self.user1,
            '999',
        )
        
        self.assertEqual(accounts.count(), 2)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)

    def test_get_sum_all_accounts(self) -> None:
        """Test get_sum_all_accounts function."""
        accounts = Account.objects.filter(user=self.user1)
        expected_sum = sum(acc.balance for acc in accounts)
        
        result = account_services.get_sum_all_accounts(accounts)
        self.assertEqual(result, expected_sum)
        self.assertEqual(result, Decimal('1500.00'))

    def test_get_sum_all_accounts_empty_queryset(self) -> None:
        """Test get_sum_all_accounts with empty queryset."""
        accounts = Account.objects.none()
        result = account_services.get_sum_all_accounts(accounts)
        self.assertEqual(result, Decimal('0.00'))

    def test_get_sum_all_accounts_single_account(self) -> None:
        """Test get_sum_all_accounts with single account."""
        accounts = Account.objects.filter(pk=self.account1.pk)
        result = account_services.get_sum_all_accounts(accounts)
        self.assertEqual(result, Decimal('1000.00'))

    def test_get_transfer_money_log(self) -> None:
        """Test get_transfer_money_log function."""
        TransferMoneyLog.objects.create(
            user=self.user1,
            from_account=self.account1,
            to_account=self.account2,
            amount=Decimal('100.00'),
            notes='Test transfer 1',
        )
        TransferMoneyLog.objects.create(
            user=self.user1,
            from_account=self.account2,
            to_account=self.account1,
            amount=Decimal('200.00'),
            notes='Test transfer 2',
        )
        TransferMoneyLog.objects.create(
            user=self.user2,
            from_account=self.account3,
            to_account=self.account1,
            amount=Decimal('300.00'),
            notes='Test transfer 3',
        )

        logs = account_services.get_transfer_money_log(self.user1)
        
        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(log.user == self.user1 for log in logs))

    def test_get_transfer_money_log_empty(self) -> None:
        """Test get_transfer_money_log with no transfers."""
        logs = account_services.get_transfer_money_log(self.user1)
        self.assertEqual(logs.count(), 0)

    def test_get_transfer_money_log_limit(self) -> None:
        """Test get_transfer_money_log with more than 10 transfers."""
        for i in range(15):
            TransferMoneyLog.objects.create(
                user=self.user1,
                from_account=self.account1,
                to_account=self.account2,
                amount=Decimal('10.00'),
                notes=f'Test transfer {i}',
            )

        logs = account_services.get_transfer_money_log(self.user1)
        self.assertLessEqual(logs.count(), 10)


class TestTransferService(TestCase):
    """Test cases for TransferService."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )
        self.from_account = Account.objects.create(
            user=self.user,
            name_account='From Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.to_account = Account.objects.create(
            user=self.user,
            name_account='To Account',
            balance=Decimal('500.00'),
            currency='RUB',
        )

    def test_transfer_service_execute_transfer(self) -> None:
        """Test TransferService execute_transfer method."""
        service = account_services.TransferService(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('200.00'),
            user=self.user,
            notes='Test transfer',
        )

        transfer_log = service.execute_transfer()

        self.assertIsInstance(transfer_log, TransferMoneyLog)
        self.assertEqual(transfer_log.from_account, self.from_account)
        self.assertEqual(transfer_log.to_account, self.to_account)
        self.assertEqual(transfer_log.amount, Decimal('200.00'))
        self.assertEqual(transfer_log.user, self.user)
        self.assertEqual(transfer_log.notes, 'Test transfer')

        self.from_account.refresh_from_db()
        self.to_account.refresh_from_db()
        self.assertEqual(self.from_account.balance, Decimal('800.00'))
        self.assertEqual(self.to_account.balance, Decimal('700.00'))

    def test_transfer_service_insufficient_funds(self) -> None:
        """Test TransferService with insufficient funds."""
        service = account_services.TransferService(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('1500.00'),
            user=self.user,
            notes='Test transfer',
        )

        with self.assertRaises(Exception):
            service.execute_transfer()

    def test_transfer_service_same_account(self) -> None:
        """Test TransferService with same account."""
        service = account_services.TransferService(
            from_account=self.from_account,
            to_account=self.from_account,
            amount=Decimal('200.00'),
            user=self.user,
            notes='Test transfer',
        )

        with self.assertRaises(Exception):
            service.execute_transfer()

    def test_transfer_service_zero_amount(self) -> None:
        """Test TransferService with zero amount."""
        service = account_services.TransferService(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('0.00'),
            user=self.user,
            notes='Test transfer',
        )

        with self.assertRaises(Exception):
            service.execute_transfer()

    def test_transfer_service_negative_amount(self) -> None:
        """Test TransferService with negative amount."""
        service = account_services.TransferService(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('-100.00'),
            user=self.user,
            notes='Test transfer',
        )

        with self.assertRaises(Exception):
            service.execute_transfer()
