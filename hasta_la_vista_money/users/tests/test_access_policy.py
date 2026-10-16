"""Единая политика доступа к данным семейной группы."""

from collections.abc import Callable
from decimal import Decimal

from django.contrib.auth.models import Group
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import FamilyGroupMembership, User
from hasta_la_vista_money.users.services.groups import (
    can_write,
    readable_users,
    remove_user_from_group,
)
from hasta_la_vista_money.users.services.monthly_statistics_service import (
    StatisticsFilters,
    _resolve_statistics_members,
)

Surface = Callable[[User, str], set[int]]


class AccessPolicyTest(TestCase):
    def setUp(self) -> None:
        names = iter(('owner', 'viewer', 'outsider', 'excluded'))
        self.owner = User.objects.create_user(username=next(names))
        self.viewer = User.objects.create_user(username=next(names))
        self.outsider = User.objects.create_user(username=next(names))
        self.excluded = User.objects.create_user(username=next(names))
        self.group = Group.objects.create(name='Family')
        for user, role in (
            (self.owner, FamilyGroupMembership.Role.OWNER),
            (self.viewer, FamilyGroupMembership.Role.VIEWER),
        ):
            FamilyGroupMembership.objects.create(
                group=self.group,
                user=user,
                role=role,
            )
        # исключённый остался в user.groups, но членства уже нет
        self.excluded.groups.add(self.group)
        self.accounts = {
            user.pk: Account.objects.create(
                user=user,
                name_account=f'acc-{user.pk}',
                balance=Decimal('10.00'),
                currency='RUB',
            )
            for user in (self.owner, self.viewer, self.outsider, self.excluded)
        }
        self.account_service = (
            ApplicationContainer().finance_account.account_service()
        )

    def _users(self, user: User, scope: str) -> set[int]:
        return {u.pk for u in readable_users(user, scope)}

    def _accounts(self, user: User, scope: str) -> set[int]:
        accounts = self.account_service.get_accounts_for_user_or_group(
            user,
            scope,
        )
        return {account.user_id for account in accounts}

    def _statistics(self, user: User, scope: str) -> set[int]:
        member = 'my' if scope == 'my' else 'family'
        filters = StatisticsFilters(member=member)
        return {u.pk for u in _resolve_statistics_members(user, filters)}

    def test_member_reads_group_others_do_not(self) -> None:
        surfaces: dict[str, Surface] = {
            'readable_users': self._users,
            'accounts': self._accounts,
            'statistics': self._statistics,
        }
        both = {self.owner.pk, self.viewer.pk}
        table = (
            (self.owner, both),
            (self.viewer, both),
            (self.outsider, {self.outsider.pk}),
            (self.excluded, {self.excluded.pk}),
        )
        for name, surface in surfaces.items():
            for user, expected in table:
                for scope in ('family', str(self.group.pk)):
                    if name == 'statistics' and scope != 'family':
                        continue
                    with self.subTest(surface=name, user=user.pk, scope=scope):
                        got = surface(user, scope)
                        if scope != 'family' and user in {
                            self.outsider,
                            self.excluded,
                        }:
                            self.assertEqual(got, set())
                        else:
                            self.assertEqual(got, expected)

    def test_my_scope_is_only_self(self) -> None:
        for user in (self.owner, self.viewer, self.outsider):
            with self.subTest(user=user.pk):
                self.assertEqual(self._users(user, 'my'), {user.pk})

    def test_family_unions_all_groups(self) -> None:
        other = Group.objects.create(name='Other')
        FamilyGroupMembership.objects.create(group=other, user=self.viewer)
        FamilyGroupMembership.objects.create(group=other, user=self.outsider)
        self.assertEqual(
            self._users(self.viewer, 'family'),
            {self.owner.pk, self.viewer.pk, self.outsider.pk},
        )

    def test_write_only_for_record_owner(self) -> None:
        account = self.accounts[self.viewer.pk]
        for user in (self.owner, self.outsider, self.excluded):
            with self.subTest(user=user.pk):
                self.assertFalse(can_write(user, account))
        self.assertTrue(can_write(self.viewer, account))

    def test_remove_uses_membership_not_user_groups(self) -> None:
        self.viewer.groups.clear()
        request = RequestFactory().post('/')
        request.session = {}  # type: ignore[assignment]
        request._messages = FallbackStorage(request)  # type: ignore[attr-defined]
        remove_user_from_group(request, self.viewer, self.group)
        self.assertFalse(
            FamilyGroupMembership.objects.filter(
                group=self.group,
                user=self.viewer,
            ).exists(),
        )

    def test_old_policy_copies_are_gone(self) -> None:
        self.assertFalse(hasattr(self.account_service, 'get_users_for_group'))
