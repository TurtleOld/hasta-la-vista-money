"""Tests for transaction and category repositories."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import ClassVar

from django.contrib.auth.models import Group
from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.transactions.repositories.category_repository import (
    CategoryRepository,
)
from hasta_la_vista_money.transactions.repositories.transaction_repository import (  # noqa: E501
    TransactionRepository,
)
from hasta_la_vista_money.users.models import User

TEST_PASSWORD = 'pwd123456!'  # nosec B105


class CategoryRepositoryTest(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.get(pk=1)
        cls.repo = CategoryRepository()
        cls.income_root = Category.objects.create(
            user=cls.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        cls.expense_root = Category.objects.create(
            user=cls.user,
            name='Дом',
            type=TransactionType.EXPENSE,
        )
        cls.expense_child = Category.objects.create(
            user=cls.user,
            name='ЖКХ',
            type=TransactionType.EXPENSE,
            parent_category=cls.expense_root,
        )

    def test_get_by_id_returns_category(self) -> None:
        self.assertEqual(
            self.repo.get_by_id(self.income_root.pk),
            self.income_root,
        )

    def test_get_by_user_without_type_returns_all(self) -> None:
        self.assertEqual(self.repo.get_by_user(self.user).count(), 3)

    def test_get_by_user_filters_by_type(self) -> None:
        self.assertEqual(
            set(self.repo.get_by_user(self.user, type_value='expense')),
            {self.expense_root, self.expense_child},
        )

    def test_get_by_user_with_related_preloads_parent(self) -> None:
        with self.assertNumQueries(1):
            result = list(
                self.repo.get_by_user_with_related(
                    self.user,
                    type_value='expense',
                ),
            )
            parent_names = [
                c.parent_category and c.parent_category.name for c in result
            ]
        self.assertIn('Дом', parent_names)

    def test_get_by_user_ordered_returns_ordered_list(self) -> None:
        ordered = list(
            self.repo.get_by_user_ordered(self.user, type_value='expense'),
        )
        self.assertEqual(ordered[0], self.expense_root)
        self.assertEqual(ordered[-1], self.expense_child)

    def test_create_category_persists_instance(self) -> None:
        created = self.repo.create_category(
            user=self.user,
            name='Топливо',
            type=TransactionType.EXPENSE,
        )
        self.assertTrue(Category.objects.filter(pk=created.pk).exists())

    def test_filter_supports_arbitrary_kwargs(self) -> None:
        self.assertEqual(
            self.repo.filter(name='ЖКХ').first(),
            self.expense_child,
        )


class TransactionRepositoryTest(TestCase):
    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
    ]

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.get(pk=1)
        cls.account = Account.objects.get(pk=1)
        cls.other_user = User.objects.create_user(
            username='other',
            password=TEST_PASSWORD,
            email='other@example.com',
        )
        cls.repo = TransactionRepository()

        cls.income_category = Category.objects.create(
            user=cls.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        cls.expense_category = Category.objects.create(
            user=cls.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )
        cls.income_jan = Transaction.objects.create(
            user=cls.user,
            account=cls.account,
            category=cls.income_category,
            amount=Decimal('1000.00'),
            date=datetime(2026, 1, 10, 12, 0, tzinfo=UTC),
            type=TransactionType.INCOME,
        )
        cls.expense_feb = Transaction.objects.create(
            user=cls.user,
            account=cls.account,
            category=cls.expense_category,
            amount=Decimal('200.00'),
            date=datetime(2026, 2, 15, 12, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )

    def test_get_by_id(self) -> None:
        self.assertEqual(
            self.repo.get_by_id(self.income_jan.pk),
            self.income_jan,
        )

    def test_get_by_user_returns_all_user_transactions(self) -> None:
        self.assertEqual(self.repo.get_by_user(self.user).count(), 2)

    def test_get_by_user_filters_by_type(self) -> None:
        self.assertEqual(
            list(self.repo.get_by_user(self.user, type_value='income')),
            [self.income_jan],
        )

    def test_get_by_user_and_group_my_returns_user_only(self) -> None:
        result = self.repo.get_by_user_and_group(self.user, group_id='my')
        self.assertEqual(result.count(), 2)

    def test_get_by_user_and_group_unknown_group_returns_empty(self) -> None:
        result = self.repo.get_by_user_and_group(
            self.user,
            group_id='9999',
        )
        self.assertEqual(list(result), [])

    def test_get_by_user_and_group_with_membership(self) -> None:
        group = Group.objects.create(name='family')
        self.user.groups.add(group)
        self.other_user.groups.add(group)
        Transaction.objects.create(
            user=self.other_user,
            account=self.account,
            category=self.expense_category,
            amount=Decimal('50.00'),
            date=datetime(2026, 2, 17, 12, 0, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )
        result = self.repo.get_by_user_and_group(
            self.user,
            group_id=str(group.id),
        )
        self.assertEqual(result.count(), 3)

    def test_get_by_period_filters_by_range(self) -> None:
        result = self.repo.get_by_period(
            self.user,
            date(2026, 2, 1),
            date(2026, 2, 28),
        )
        self.assertEqual(list(result), [self.expense_feb])

    def test_filter_by_user_and_date_range_with_type(self) -> None:
        result = self.repo.filter_by_user_and_date_range(
            self.user,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 12, 31, tzinfo=UTC),
            type_value='expense',
        )
        self.assertEqual(list(result), [self.expense_feb])

    def test_get_by_category(self) -> None:
        result = self.repo.get_by_category(self.user, self.expense_category)
        self.assertEqual(list(result), [self.expense_feb])

    def test_get_by_account(self) -> None:
        result = self.repo.get_by_account(
            self.user,
            self.account.pk,
            type_value='income',
        )
        self.assertEqual(list(result), [self.income_jan])

    def test_filter_by_account(self) -> None:
        result = self.repo.filter_by_account(self.account)
        self.assertEqual(result.count(), 2)

    def test_create_transaction_normalises_naive_date(self) -> None:
        created = self.repo.create_transaction(
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1.00'),
            date=date(2026, 3, 5),
            type='income',
        )
        self.assertEqual(created.date.year, 2026)
        self.assertIsNotNone(created.date.tzinfo)

    def test_create_transaction_makes_naive_datetime_aware(self) -> None:
        aware = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
        naive = aware.replace(tzinfo=None)
        created = self.repo.create_transaction(
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1.00'),
            date=naive,
            type='income',
        )
        self.assertIsNotNone(created.date.tzinfo)

    def test_filter_with_select_related(self) -> None:
        result = self.repo.filter_with_select_related(
            'category',
            user=self.user,
        )
        self.assertEqual(result.count(), 2)

    def test_get_aggregated_by_date(self) -> None:
        rows = list(self.repo.get_aggregated_by_date(self.user))
        self.assertEqual(len(rows), 2)

    def test_get_top_categories(self) -> None:
        rows = list(
            self.repo.get_top_categories(
                self.user,
                datetime(2026, 1, 1, tzinfo=UTC),
                type_value='expense',
            ),
        )
        self.assertEqual(rows[0]['category__id'], self.expense_category.pk)

    def test_filter_by_user_category_and_month(self) -> None:
        result = self.repo.filter_by_user_category_and_month(
            self.user,
            self.expense_category,
            date(2026, 2, 1),
        )
        self.assertEqual(list(result), [self.expense_feb])

    def test_aggregate_by_month(self) -> None:
        rows = list(
            self.repo.aggregate_by_month(
                self.user,
                account=self.account,
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=datetime(2026, 12, 31, tzinfo=UTC),
                type_value='expense',
            ),
        )
        self.assertEqual(rows[0]['total'], Decimal('200.00'))
