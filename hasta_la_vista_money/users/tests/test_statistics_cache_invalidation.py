from datetime import UTC, date, datetime
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase

from hasta_la_vista_money.budget.models import Budget, Planning
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import ProductCategory
from hasta_la_vista_money.receipts.repositories import ProductRepository
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import FamilyGroupMembership, User
from hasta_la_vista_money.users.services.cache import (
    get_user_detailed_statistics_cache_key,
    invalidate_user_detailed_statistics_cache,
)


class StatisticsVersionResetTest(TestCase):
    def test_lost_version_key_does_not_revive_old_cache_keys(self) -> None:
        user_id = 987654
        initial = get_user_detailed_statistics_cache_key(user_id)
        invalidate_user_detailed_statistics_cache(user_id)
        invalidated = get_user_detailed_statistics_cache_key(user_id)

        # Ключ версии истёк или вытеснен из кеша.
        cache.delete(f'user_stats_version_{user_id}')

        self.assertNotIn(
            get_user_detailed_statistics_cache_key(user_id),
            {initial, invalidated},
        )


class StatisticsCacheInvalidationTest(TestCase):
    def setUp(self) -> None:
        self.a = User.objects.create_user(username='cache-a', password='x')
        self.b = User.objects.create_user(username='cache-b', password='x')
        self.outsider = User.objects.create_user(
            username='cache-out',
            password='x',
        )
        self.group = Group.objects.create(name='cache-family')
        for user, role in (
            (self.a, FamilyGroupMembership.Role.OWNER),
            (self.b, FamilyGroupMembership.Role.VIEWER),
        ):
            FamilyGroupMembership.objects.create(
                group=self.group,
                user=user,
                role=role,
            )
        self.category = Category.objects.create(
            user=self.b,
            name='cache-category',
            type=TransactionType.EXPENSE,
        )

    def _key(self, user: User) -> str:
        return get_user_detailed_statistics_cache_key(user.pk)

    def test_member_transaction_resets_cache_of_group_members(self) -> None:
        account = Account.objects.create(
            user=self.b,
            name_account='cache-acc',
            balance=Decimal('100.00'),
            currency='RUB',
        )
        before = {u: self._key(u) for u in (self.a, self.b, self.outsider)}

        with self.captureOnCommitCallbacks(execute=True):
            Transaction.objects.create(
                user=self.b,
                account=account,
                category=self.category,
                type=TransactionType.EXPENSE,
                amount=Decimal('10.00'),
                date=datetime(2026, 1, 10, 12, 0, tzinfo=UTC),
            )

        self.assertNotEqual(before[self.a], self._key(self.a))
        self.assertNotEqual(before[self.b], self._key(self.b))
        self.assertEqual(before[self.outsider], self._key(self.outsider))

    def test_budget_limit_change_resets_cache(self) -> None:
        before = self._key(self.a)

        with self.captureOnCommitCallbacks(execute=True):
            Budget.objects.create(
                user=self.b,
                category=self.category,
                period=date(2026, 1, 1),
                amount_limit=Decimal('500.00'),
            )

        self.assertNotEqual(before, self._key(self.a))

    def test_planning_change_resets_cache(self) -> None:
        before = self._key(self.a)

        with self.captureOnCommitCallbacks(execute=True):
            Planning.objects.create(
                user=self.b,
                category=self.category,
                date=date(2026, 1, 1),
                amount=Decimal('500.00'),
                planning_type=TransactionType.EXPENSE,
            )

        self.assertNotEqual(before, self._key(self.a))

    def test_removing_member_resets_cache_of_everyone(self) -> None:
        before = {u: self._key(u) for u in (self.a, self.b, self.outsider)}

        with self.captureOnCommitCallbacks(execute=True):
            FamilyGroupMembership.objects.filter(
                group=self.group,
                user=self.b,
            ).delete()

        self.assertNotEqual(before[self.a], self._key(self.a))
        self.assertNotEqual(before[self.b], self._key(self.b))
        self.assertEqual(before[self.outsider], self._key(self.outsider))

    def test_product_category_move_resets_owner_cache(self) -> None:
        source = ProductCategory.objects.create(
            user=self.b,
            name='src',
            normalized_name='src',
        )
        target = ProductCategory.objects.create(
            user=self.b,
            name='dst',
            normalized_name='dst',
        )
        before = self._key(self.a)

        with self.captureOnCommitCallbacks(execute=True):
            ProductRepository().move_category(
                user=self.b,
                from_category=source,
                to_category=target,
            )

        self.assertNotEqual(before, self._key(self.a))
