"""Tests for finance account services."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from unittest import mock

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.factories import (
    AccountFactory,
    TransferMoneyLogFactory,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.users.factories import UserFactory

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    from django.contrib.auth import get_user_model

    UserType = get_user_model()


class TestAccountServices(TestCase):
    """Test cases for account service functions."""

    def setUp(self) -> None:
        self.user1: UserType = cast('UserType', UserFactory())
        self.user2: UserType = cast('UserType', UserFactory())
        self.container = ApplicationContainer()
        self.account_service = self.container.finance_account.account_service()

        self.account1: Account = cast(
            'Account',
            AccountFactory(user=self.user1, balance=Decimal('1000.00')),
        )
        self.account2: Account = cast(
            'Account',
            AccountFactory(user=self.user1, balance=Decimal('500.00')),
        )
        self.account3: Account = cast(
            'Account',
            AccountFactory(user=self.user2, balance=Decimal('2000.00')),
        )

    def test_get_accounts_for_user_or_group_none(self) -> None:
        """Test get_accounts_for_user_or_group with None group_id."""
        accounts = self.account_service.get_accounts_for_user_or_group(
            self.user1,
            None,
        )

        self.assertEqual(accounts.count(), 2)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertNotIn(self.account3, accounts)

    def test_get_accounts_for_user_or_group_my(self) -> None:
        """Test get_accounts_for_user_or_group with 'my' group_id."""
        accounts = self.account_service.get_accounts_for_user_or_group(
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

        accounts = self.account_service.get_accounts_for_user_or_group(
            self.user1,
            str(group.pk),
        )

        self.assertEqual(accounts.count(), 3)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)
        self.assertIn(self.account3, accounts)

    def test_get_accounts_for_user_or_group_invalid_group(self) -> None:
        """Test get_accounts_for_user_or_group with invalid group_id."""
        accounts = self.account_service.get_accounts_for_user_or_group(
            self.user1,
            '999',
        )

        # When group doesn't exist, should return only user's own accounts
        self.assertEqual(accounts.count(), 2)
        self.assertIn(self.account1, accounts)
        self.assertIn(self.account2, accounts)

    def test_get_sum_all_accounts(self) -> None:
        """Test get_sum_all_accounts function."""
        accounts = Account.objects.filter(user=self.user1)
        expected_sum = sum(acc.balance for acc in accounts)

        result = self.account_service.get_sum_all_accounts(accounts)
        self.assertEqual(result, expected_sum)
        self.assertEqual(result, Decimal('1500.00'))

    def test_get_sum_all_accounts_empty_queryset(self) -> None:
        """Test get_sum_all_accounts with empty queryset."""
        accounts = Account.objects.none()
        result = self.account_service.get_sum_all_accounts(accounts)
        self.assertEqual(result, Decimal('0.00'))

    def test_get_sum_all_accounts_single_account(self) -> None:
        """Test get_sum_all_accounts with single account."""
        accounts = Account.objects.filter(pk=self.account1.pk)
        result = self.account_service.get_sum_all_accounts(accounts)
        self.assertEqual(result, Decimal('1000.00'))

    def test_get_sum_all_accounts_parametrized(self) -> None:
        """Test parametrized sum calculation with different account sets.

        Tests boundary conditions, precision, and currency handling.
        """
        testcases = [
            {
                'balances': [Decimal('1000.00'), Decimal('500.00')],
                'expected': Decimal('1500.00'),
            },
            {'balances': [Decimal('123.45')], 'expected': Decimal('123.45')},
            {'balances': [], 'expected': Decimal('0.00')},
            {
                'balances': [Decimal('0.1'), Decimal('0.2')],
                'expected': Decimal('0.3'),
            },
            {
                'balances': [Decimal('1000000000.00'), Decimal('0.01')],
                'expected': Decimal('1000000000.01'),
            },
        ]
        for case in testcases:
            with self.subTest(balances=case['balances']):
                balances_list: list[Decimal] = cast(
                    'list[Decimal]',
                    case['balances'],
                )
                accounts_list: list[Account] = [
                    cast(
                        'Account',
                        AccountFactory(
                            user=self.user1,
                            balance=bal,
                            currency='RUB',
                        ),
                    )
                    for bal in balances_list
                ]
                qs = Account.objects.filter(
                    pk__in=[acc.pk for acc in accounts_list],
                )
                result = self.account_service.get_sum_all_accounts(qs)
                self.assertEqual(result, case['expected'])

        acc1 = cast(
            'Account',
            AccountFactory(
                user=self.user1,
                balance=Decimal('100.00'),
                currency='RUB',
            ),
        )
        acc2 = cast(
            'Account',
            AccountFactory(
                user=self.user1,
                balance=Decimal('200.00'),
                currency='USD',
            ),
        )
        qs = Account.objects.filter(pk__in=[acc1.pk, acc2.pk])
        result = self.account_service.get_sum_all_accounts(qs)
        self.assertEqual(result, Decimal('300.00'))

    def test_get_transfer_money_log(self) -> None:
        """Test get_transfer_money_log function."""
        TransferMoneyLogFactory(
            user=self.user1,
            from_account=self.account1,
            to_account=self.account2,
            amount=Decimal('100.00'),
        )
        TransferMoneyLogFactory(
            user=self.user1,
            from_account=self.account2,
            to_account=self.account1,
            amount=Decimal('200.00'),
        )
        TransferMoneyLogFactory(
            user=self.user2,
            from_account=self.account3,
            to_account=self.account1,
            amount=Decimal('300.00'),
        )

        logs = self.account_service.get_transfer_money_log(self.user1)

        self.assertEqual(logs.count(), 2)
        self.assertTrue(all(log.user == self.user1 for log in logs))

    def test_get_transfer_money_log_empty(self) -> None:
        """Test get_transfer_money_log with no transfers."""
        logs = self.account_service.get_transfer_money_log(self.user1)
        self.assertEqual(logs.count(), 0)

    def test_get_transfer_money_log_limit(self) -> None:
        """Test get_transfer_money_log with more than 10 transfers."""
        for _ in range(15):
            TransferMoneyLogFactory(
                user=self.user1,
                from_account=self.account1,
                to_account=self.account2,
                amount=Decimal('10.00'),
            )

        logs = self.account_service.get_transfer_money_log(self.user1)
        self.assertLessEqual(logs.count(), 10)


class TestTransferService(TestCase):
    """Test cases for TransferService."""

    def setUp(self) -> None:
        self.user: UserType = cast('UserType', UserFactory())
        self.container = ApplicationContainer()
        self.transfer_service = (
            self.container.finance_account.transfer_service()
        )
        self.from_account: Account = cast(
            'Account',
            AccountFactory(
                user=self.user,
                balance=Decimal('1000.00'),
            ),
        )
        self.to_account: Account = cast(
            'Account',
            AccountFactory(
                user=self.user,
                balance=Decimal('500.00'),
            ),
        )

    def test_transfer_service_execute_transfer(self) -> None:
        """Test TransferService execute_transfer method."""
        transfer_log = self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('200.00'),
            user=self.user,
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='Test transfer',
        )

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
        with self.assertRaises(ValidationError):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=self.to_account,
                amount=Decimal('1500.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Test transfer',
            )

    def test_transfer_service_same_account(self) -> None:
        """Test TransferService with same account."""
        with self.assertRaises(ValidationError):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=self.from_account,
                amount=Decimal('200.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Test transfer',
            )

    def test_transfer_service_invalid_amounts_parametrized(self) -> None:
        """Boundary: zero and negative amounts should be rejected."""
        invalid_amounts = [
            Decimal('0.00'),
            Decimal('-0.01'),
            Decimal('-100.00'),
        ]
        for amount in invalid_amounts:
            with (
                self.subTest(amount=amount),
                self.assertRaises(ValidationError),
            ):
                self.transfer_service.transfer_money(
                    from_account=self.from_account,
                    to_account=self.to_account,
                    amount=amount,
                    user=self.user,
                    exchange_date=datetime(
                        2024,
                        1,
                        1,
                        tzinfo=timezone.get_current_timezone(),
                    ),
                    notes='Test transfer',
                )

    def test_transfer_service_amount_equals_balance_boundary(self) -> None:
        """Boundary: transferring exactly available balance should succeed."""
        transfer_amount = self.from_account.balance
        self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=transfer_amount,
            user=self.user,
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='All funds',
        )

        self.from_account.refresh_from_db()
        self.to_account.refresh_from_db()
        self.assertEqual(self.from_account.balance, Decimal('0.00'))
        self.assertEqual(self.to_account.balance, Decimal('1500.00'))

    def test_transfer_is_atomic_when_log_creation_fails(self) -> None:
        """If log creation fails, transfer is rolled back completely."""
        original_from = self.from_account.balance
        original_to = self.to_account.balance

        with (
            mock.patch(
                'hasta_la_vista_money.finance_account.repositories.transfer_money_log_repository.TransferMoneyLogRepository.create_log',
                side_effect=RuntimeError('fail on create'),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=self.to_account,
                amount=Decimal('200.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Should rollback',
            )

        self.from_account.refresh_from_db()
        self.to_account.refresh_from_db()
        self.assertEqual(self.from_account.balance, original_from)
        self.assertEqual(self.to_account.balance, original_to)

    def test_sequential_large_transfers_only_first_succeeds(self) -> None:
        """Test two sequential large transfers: second should fail."""
        self.transfer_service.transfer_money(
            from_account=self.from_account,
            to_account=self.to_account,
            amount=Decimal('700.00'),
            user=self.user,
            exchange_date=datetime(
                2024,
                1,
                1,
                tzinfo=timezone.get_current_timezone(),
            ),
            notes='First',
        )

        with self.assertRaises(ValidationError):
            self.transfer_service.transfer_money(
                from_account=self.from_account,
                to_account=self.to_account,
                amount=Decimal('700.00'),
                user=self.user,
                exchange_date=datetime(
                    2024,
                    1,
                    1,
                    tzinfo=timezone.get_current_timezone(),
                ),
                notes='Second',
            )

        logs = TransferMoneyLog.objects.filter(user=self.user)
        self.assertEqual(logs.count(), 1)
