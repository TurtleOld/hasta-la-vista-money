"""Единая политика доступа к данным семейной группы."""

import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from config.containers import ApplicationContainer
from hasta_la_vista_money.deposits.models import Deposit, DepositTerm
from hasta_la_vista_money.finance_account.models import Account, Bank
from hasta_la_vista_money.receipts.models import Receipt, Seller
from hasta_la_vista_money.system.audit_registry import ACCOUNT_LABEL
from hasta_la_vista_money.system.models import AuditLog
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
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

# Поверхности, которые читают данные группы через readable_users.
GROUP_READ_SURFACES = frozenset(
    {
        'budget:expense_budget',
        'budget:expense_table',
        'budget:income_budget',
        'budget:income_table',
        'budget:list',
        'deposits:detail',
        'finance_account:by_group',
        'finance_account:list',
        'finances',
        'receipts:by_group',
        'receipts:list',
        'receipts:view',
        'system:auditlog',
        'system:auditlog_operation',
        'transactions:by_group',
        'transactions:data',
        'transactions:retrieve',
        'users:dashboard',
        'users:export_data',
        'users:statistics',
        'users:statistics_export',
    },
)
# Запись (только владелец записи), чтение только своих данных или служебное.
OWN_ONLY_SURFACES = frozenset(
    {
        'authentication:token',
        'authentication:token_refresh',
        'authentication:token_session',
        'budget:change_planning',
        'budget:generate_date',
        'budget:save_limit',
        'budget:save_planning',
        'deposits:add-rate-period',
        'deposits:capitalize',
        'deposits:close',
        'deposits:correct-schedule',
        'deposits:create',
        'deposits:early-close',
        'deposits:list',
        'deposits:recalculate-forecast',
        'deposits:reconcile',
        'deposits:renew',
        'deposits:reverse-event',
        'deposits:top-up',
        'deposits:withdraw',
        'finance_account:adjust_balance',
        'finance_account:api_detail',
        'finance_account:api_list',
        'finance_account:archive',
        'finance_account:change',
        'finance_account:create',
        'finance_account:delete_account',
        'finance_account:quick_bank',
        'finance_account:quick_category',
        'finance_account:transaction_change',
        'finance_account:transaction_copy',
        'finance_account:transaction_delete',
        'finance_account:transfer_delete',
        'finance_account:unarchive',
        'finance_account:transfer_money',
        'finances_categories',
        'finances_create',
        'healthz',
        'index',
        # кредиты: без detail и выбора группы, область группы не нужна
        'loan:create',
        'loan:delete',
        'loan:list',
        'loan:payment_create',
        'loan:payment_delete',
        'login',
        'logout',
        'offline',
        'readyz',
        'receipts:api_list',
        'receipts:category_twins',
        'receipts:category_twins_keep',
        'receipts:category_twins_merge',
        'receipts:create',
        'receipts:create_seller',
        'receipts:delete',
        'receipts:delete_api',
        'receipts:processing_delete',
        'receipts:processing_notifications',
        'receipts:processing_retry',
        'receipts:product_autocomplete_api',
        'receipts:products',
        'receipts:receipt_api_create',
        'receipts:receipt_image',
        'receipts:scan_qr_api',
        'receipts:seller',
        'receipts:seller_autocomplete_api',
        'receipts:seller_create_api',
        'receipts:update',
        'receipts:update_seller',
        'receipts:upload',
        'service_worker',
        'service_worker_precache',
        'transactions:category_list',
        'transactions:create_category',
        'transactions:delete_category',
        'transactions:update_category',
        'users:ajax:groups_for_user',
        'users:ajax:groups_not_for_user',
        'users:available_groups',
        'finance_account:bank_statement_markup',
        'finance_account:bank_statement_markup_bulk',
        'finance_account:bank_statement_markup_category',
        'finance_account:bank_statement_markup_decide',
        'finance_account:bank_statement_markup_post_remembered',
        'finance_account:bank_statement_pending_transfer_dismiss',
        'finance_account:bank_statement_pending_transfer_link',
        'finance_account:bank_statement_reconciliation',
        'finance_account:bank_statement_reconciliation_bulk',
        'finance_account:bank_statement_reconciliation_decide',
        'finance_account:bank_statement_reconciliation_revise',
        'finance_account:bank_statement_upload',
        'finance_account:bank_statement_upload_status',
        'users:dashboard_comparison',
        'users:dashboard_data',
        'users:dashboard_drilldown',
        'users:dashboard_widget',
        'users:groups',
        'users:groups:create',
        'users:groups:delete',
        'users:groups:delete_user',
        'users:groups:join',
        'users:groups:register_by_invite',
        'users:list_users',
        'users:login',
        'users:password',
        'users:profile',
        'users:registration',
        'users:set_theme',
        'users:statistics_receipts_category_products',
        'users:statistics_receipts_product_purchases',
        'users:update_user',
    },
)


def _project_url_names(
    patterns: list[URLPattern | URLResolver],
    namespace: str = '',
) -> set[str]:
    """Имена URL всех view и API проекта; ``api:`` дублирует веб-маршруты."""
    names: set[str] = set()
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            prefix = f'{pattern.namespace}:' if pattern.namespace else ''
            if prefix == 'api:':
                prefix = ''
            names |= _project_url_names(
                pattern.url_patterns,
                namespace + prefix,
            )
        elif pattern.callback.__module__.startswith('hasta_la_vista_money'):
            names.add(f'{namespace}{pattern.name}')
    return names


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

    def _detail_urls(self) -> dict[str, str]:
        owner = self.owner
        seller = Seller.objects.create(user=owner, name_seller='shop')
        receipt = Receipt.objects.create(
            user=owner,
            account=self.accounts[owner.pk],
            seller=seller,
            receipt_date=timezone.now(),
            operation_type=1,
            total_sum=Decimal('10.00'),
        )
        deposit_account = Account.objects.create_deposit(
            user=owner,
            name_account='deposit',
            bank=Bank.objects.get(code='SBERBANK'),
            currency='RUB',
            balance=Decimal('100.00'),
        )
        deposit = Deposit.objects.create(
            account=deposit_account,
            name='deposit',
            bank=deposit_account.bank,
        )
        today = timezone.localdate()
        DepositTerm.objects.create(
            deposit=deposit,
            opened_on=today,
            matures_on=today + timedelta(days=30),
            is_current=True,
            rate_kind=DepositTerm.RateKind.FIXED,
        )
        category = Category.objects.create(
            user=owner,
            name='food',
            type=TransactionType.EXPENSE,
        )
        transaction = Transaction.objects.create(
            user=owner,
            account=self.accounts[owner.pk],
            category=category,
            amount=Decimal('1.00'),
            date=timezone.now(),
            type=TransactionType.EXPENSE,
        )
        operation = AuditLog.objects.create(
            user=owner,
            operation_id=uuid.uuid4(),
            model_name=ACCOUNT_LABEL,
            object_pk=str(self.accounts[owner.pk].pk),
            action=AuditLog.Action.CREATE,
            diff={'v': 2, 'created': {'balance': '10.00'}},
        )
        group_scope = f'?group_id={self.group.pk}'
        return {
            'audit_feed': reverse('system:auditlog') + group_scope,
            'audit_operation': reverse(
                'system:auditlog_operation',
                args=[str(operation.operation_id)],
            ),
            'export': reverse('users:export_data') + group_scope,
            'receipt': reverse('receipts:view', args=[receipt.pk]),
            'deposit': reverse('deposits:detail', args=[deposit.pk]),
            'transaction_api': reverse(
                'api:transactions:retrieve',
                args=[transaction.pk],
            ),
        }

    def test_detail_surfaces_follow_policy(self) -> None:
        urls = self._detail_urls()
        table = (
            (self.owner, status.HTTP_200_OK),
            (self.viewer, status.HTTP_200_OK),
            (self.outsider, status.HTTP_404_NOT_FOUND),
            (self.excluded, status.HTTP_404_NOT_FOUND),
        )
        for user, expected in table:
            client = APIClient()
            client.force_login(user)
            client.force_authenticate(user=user)
            for name, url in urls.items():
                with self.subTest(surface=name, user=user.username):
                    self.assertEqual(client.get(url).status_code, expected)

    def test_viewer_cannot_write_through_detail_surfaces(self) -> None:
        urls = self._detail_urls()
        deposit_pk = urls['deposit'].rstrip('/').rsplit('/', 1)[-1]
        receipt_pk = urls['receipt'].rstrip('/').rsplit('/', 1)[-1]
        self.client.force_login(self.viewer)
        for name, url in (
            ('reconcile', reverse('deposits:reconcile', args=[deposit_pk])),
            ('delete', reverse('receipts:delete', args=[receipt_pk])),
        ):
            with self.subTest(action=name):
                self.assertEqual(
                    self.client.post(url).status_code,
                    status.HTTP_404_NOT_FOUND,
                )

    def test_every_view_is_in_policy_table(self) -> None:
        self.assertFalse(GROUP_READ_SURFACES & OWN_ONLY_SURFACES)
        missing = _project_url_names(get_resolver().url_patterns) - (
            GROUP_READ_SURFACES | OWN_ONLY_SURFACES
        )
        self.assertEqual(missing, set(), 'Внесите view в таблицу политики')
        self.assertLessEqual(
            {
                'receipts:view',
                'deposits:detail',
                'transactions:retrieve',
                'system:auditlog',
                'system:auditlog_operation',
                'users:export_data',
            },
            GROUP_READ_SURFACES,
        )

    def test_audit_and_export_show_group_only_on_explicit_scope(self) -> None:
        urls = self._detail_urls()
        self.client.force_login(self.viewer)
        feed = self.client.get(urls['audit_feed'])
        self.assertContains(feed, urls['audit_operation'])
        self.assertContains(feed, f'caption">{self.owner.username}<')
        own_feed = self.client.get(reverse('system:auditlog'))
        self.assertNotContains(own_feed, urls['audit_operation'])

        exported = json.loads(self.client.get(urls['export']).content)
        self.assertEqual(
            [row['owner'] for row in exported['expenses']],
            [self.owner.username],
        )
        self.assertEqual(
            {row['owner'] for row in exported['accounts']},
            {self.owner.username, self.viewer.username},
        )
        own = json.loads(self.client.get(reverse('users:export_data')).content)
        self.assertEqual(own['expenses'], [])
        self.assertEqual(
            [row['owner'] for row in own['accounts']],
            [self.viewer.username],
        )

    def test_viewer_sees_no_write_buttons_on_detail_pages(self) -> None:
        urls = self._detail_urls()
        receipt_pk = urls['receipt'].rstrip('/').rsplit('/', 1)[-1]
        deposit_pk = urls['deposit'].rstrip('/').rsplit('/', 1)[-1]
        write_urls = {
            'receipt': (
                reverse('receipts:delete', args=[receipt_pk]),
                reverse('receipts:update', args=[receipt_pk]),
            ),
            'deposit': (
                reverse('deposits:reconcile', args=[deposit_pk]),
                reverse('deposits:top-up', args=[deposit_pk]),
            ),
        }
        for user, visible in ((self.owner, True), (self.viewer, False)):
            self.client.force_login(user)
            for page, actions in write_urls.items():
                html = self.client.get(urls[page]).content.decode()
                for action in actions:
                    with self.subTest(user=user.username, action=action):
                        self.assertEqual(f'"{action}"' in html, visible)

    def test_archival_operation_keeps_only_its_owner(self) -> None:
        anchor, other = (
            AuditLog.objects.create(
                user=user,
                model_name=ACCOUNT_LABEL,
                object_pk=str(self.accounts[user.pk].pk),
                object_name=user.username,
                action=AuditLog.Action.CREATE,
                diff={'v': 2, 'created': {'name_account': user.username}},
            )
            for user in (self.owner, self.viewer)
        )
        AuditLog.objects.filter(pk=other.pk).update(
            created_at=anchor.created_at,
        )
        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse('system:auditlog_operation', args=[str(anchor.pk)]),
        )
        self.assertContains(response, self.owner.username)
        self.assertNotContains(response, f'«{self.viewer.username}»')
