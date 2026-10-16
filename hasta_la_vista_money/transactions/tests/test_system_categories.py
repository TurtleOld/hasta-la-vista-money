"""Tests for protected «Корректировка остатка» system categories."""

from django.contrib import admin
from django.db import IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.signals import post_save
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.forms import TransactionForm
from hasta_la_vista_money.transactions.models import (
    Category,
    SystemCategoryKind,
    TransactionType,
)
from hasta_la_vista_money.transactions.services.signals import (
    seed_system_categories_for_new_user,
)
from hasta_la_vista_money.users.models import User

TEST_PASSWORD = 'pwd123456!'  # nosec B105


def _system(user: User, type_value: str) -> Category:
    return Category.objects.get(
        user=user,
        type=type_value,
        system_kind=SystemCategoryKind.BALANCE_ADJUSTMENT,
    )


class SystemCategoryTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='sys-user',
            password=TEST_PASSWORD,
        )
        self.client.login(username='sys-user', password=TEST_PASSWORD)

    def test_new_user_gets_both_system_categories(self) -> None:
        for type_value in TransactionType.values:
            self.assertEqual(
                _system(self.user, type_value).name,
                constants.BALANCE_ADJUSTMENT_CATEGORY_NAME,
            )

    def test_second_system_category_of_same_kind_and_type_rejected(
        self,
    ) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(
                user=self.user,
                name='Другая',
                type=TransactionType.EXPENSE,
                system_kind=SystemCategoryKind.BALANCE_ADJUSTMENT,
            )

    def test_delete_system_category_refused(self) -> None:
        category = _system(self.user, TransactionType.EXPENSE)
        self.client.post(
            reverse('transactions:delete_category', args=[category.pk]),
        )
        self.assertTrue(Category.objects.filter(pk=category.pk).exists())

    def test_rename_system_category_refused(self) -> None:
        category = _system(self.user, TransactionType.EXPENSE)
        self.client.post(
            reverse('transactions:update_category', args=[category.pk]),
            data={'name': 'Иное', 'type': 'expense'},
        )
        category.refresh_from_db()
        self.assertEqual(
            category.name,
            constants.BALANCE_ADJUSTMENT_CATEGORY_NAME,
        )

    def test_system_category_not_selectable_in_transaction_form(self) -> None:
        account = Account.objects.create(
            user=self.user,
            name_account='acc',
            balance=100,
            currency='RUB',
        )
        system = _system(self.user, TransactionType.EXPENSE)
        form = TransactionForm(
            {
                'type': 'expense',
                'category': system.pk,
                'account': account.pk,
                'date': timezone.now().strftime('%Y-%m-%dT%H:%M'),
                'amount': '10',
            },
            category_queryset=Category.objects.filter(user=self.user),
            account_queryset=Account.objects.filter(user=self.user),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('category', form.errors)

    def test_quick_create_refuses_system_category_name(self) -> None:
        response = self.client.post(
            reverse('finance_account:quick_category'),
            data={
                'type': 'expense',
                'name': constants.BALANCE_ADJUSTMENT_CATEGORY_NAME,
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_makes_system_category_read_only(self) -> None:
        model_admin = admin.site._registry[Category]
        request = RequestFactory().get('/')
        system = _system(self.user, TransactionType.EXPENSE)
        regular = Category.objects.create(
            user=self.user,
            name='Обычная',
            type=TransactionType.EXPENSE,
        )
        self.assertIn(
            'name',
            model_admin.get_readonly_fields(request, system),
        )
        self.assertFalse(model_admin.has_delete_permission(request, system))
        self.assertNotIn(
            'name',
            model_admin.get_readonly_fields(request, regular),
        )


class SystemCategoryMigrationTest(TransactionTestCase):
    migrate_from = [
        ('transactions', '0004_transaction_description'),
    ]
    migrate_to = [
        ('transactions', '0006_seed_balance_adjustment_categories'),
    ]

    def setUp(self) -> None:
        self.executor = MigrationExecutor(transaction.get_connection())
        self.executor.migrate(self.migrate_from)
        old_apps = self.executor.loader.project_state(self.migrate_from).apps
        self.old_category = old_apps.get_model('transactions', 'Category')
        post_save.disconnect(seed_system_categories_for_new_user, sender=User)
        self.user = User.objects.create_user(
            username='migration-user',
            password=TEST_PASSWORD,
            theme='auto',
        )

    def tearDown(self) -> None:
        self.executor = MigrationExecutor(transaction.get_connection())
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        post_save.connect(seed_system_categories_for_new_user, sender=User)

    def _migrate(self) -> type[Category]:
        self.executor = MigrationExecutor(transaction.get_connection())
        self.executor.migrate(self.migrate_to)
        apps = self.executor.loader.project_state(self.migrate_to).apps
        return apps.get_model('transactions', 'Category')

    def test_legacy_category_becomes_system_oldest_wins(self) -> None:
        oldest = self.old_category.objects.create(
            user_id=self.user.pk,
            name='корректировка баланса',
            type='expense',
        )
        self.old_category.objects.create(
            user_id=self.user.pk,
            name='Корректировка остатка',
            type='expense',
        )
        category_model = self._migrate()

        system = category_model.objects.get(
            user_id=self.user.pk,
            type='expense',
            system_kind='balance_adjustment',
        )
        self.assertEqual(system.pk, oldest.pk)
        self.assertEqual(system.name, 'Корректировка остатка')
        self.assertEqual(
            category_model.objects.filter(
                user_id=self.user.pk,
                type='expense',
            ).count(),
            2,
        )

    def test_missing_system_category_is_created(self) -> None:
        category_model = self._migrate()

        for type_value in ('income', 'expense'):
            self.assertEqual(
                category_model.objects.filter(
                    user_id=self.user.pk,
                    type=type_value,
                    system_kind='balance_adjustment',
                    name='Корректировка остатка',
                ).count(),
                1,
            )
