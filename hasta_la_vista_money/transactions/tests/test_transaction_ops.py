"""Tests for TransactionService and CategoryService."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import ClassVar
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.forms import CategoryForm
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
from hasta_la_vista_money.transactions.services.category_ops import (
    CategoryService,
)
from hasta_la_vista_money.transactions.services.transaction_ops import (
    TransactionService,
)
from hasta_la_vista_money.users.models import User


class TransactionServiceTest(TestCase):
    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.account.user = self.user
        self.account.balance = Decimal('1000.00')
        self.account.save()

        self.income_category = Category.objects.create(
            user=self.user,
            name='Зарплата',
            type=TransactionType.INCOME,
        )
        self.expense_category = Category.objects.create(
            user=self.user,
            name='Еда',
            type=TransactionType.EXPENSE,
        )

        container = ApplicationContainer()
        self.service = TransactionService(
            account_service=container.core.account_service(),
            transaction_repository=TransactionRepository(),
        )

    def test_add_income_increases_account_balance(self) -> None:
        with patch(
            'hasta_la_vista_money.transactions.services.transaction_ops.invalidate_user_detailed_statistics_cache',
        ):
            self.service.add_transaction(
                user=self.user,
                account=self.account,
                category=self.income_category,
                amount=Decimal('500.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.INCOME,
            )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1500.00'))

    def test_add_expense_decreases_account_balance(self) -> None:
        with patch(
            'hasta_la_vista_money.transactions.services.transaction_ops.invalidate_user_detailed_statistics_cache',
        ):
            self.service.add_transaction(
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('200.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.EXPENSE,
            )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('800.00'))

    def test_add_rejects_account_owned_by_another_user(self) -> None:
        other = User.objects.create_user(
            username='other',
            password='pwd123456!',
            email='o@example.com',
        )
        with self.assertRaises(PermissionDenied):
            self.service.add_transaction(
                user=other,
                account=self.account,
                category=self.income_category,
                amount=Decimal('1.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.INCOME,
            )

    def test_add_rejects_type_mismatched_category(self) -> None:
        with self.assertRaises(ValueError):
            self.service.add_transaction(
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('1.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.INCOME,
            )

    def test_update_changes_amount_and_reverses_old(self) -> None:
        with patch(
            'hasta_la_vista_money.transactions.services.transaction_ops.invalidate_user_detailed_statistics_cache',
        ):
            tx = self.service.add_transaction(
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('200.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.EXPENSE,
            )
            self.service.update_transaction(
                user=self.user,
                transaction_obj=tx,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('300.00'),
                transaction_date=date(2026, 4, 2),
                type_value=TransactionType.EXPENSE,
            )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('700.00'))

    def test_update_rejects_foreign_transaction(self) -> None:
        with patch(
            'hasta_la_vista_money.transactions.services.transaction_ops.invalidate_user_detailed_statistics_cache',
        ):
            tx = self.service.add_transaction(
                user=self.user,
                account=self.account,
                category=self.income_category,
                amount=Decimal('10.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.INCOME,
            )
        other = User.objects.create_user(
            username='ext',
            password='pwd123456!',
            email='e@example.com',
        )
        with self.assertRaises(PermissionDenied):
            self.service.update_transaction(
                user=other,
                transaction_obj=tx,
                account=self.account,
                category=self.income_category,
                amount=Decimal('20.00'),
                transaction_date=date(2026, 4, 2),
                type_value=TransactionType.INCOME,
            )

    def test_delete_reverses_balance(self) -> None:
        with patch(
            'hasta_la_vista_money.transactions.services.transaction_ops.invalidate_user_detailed_statistics_cache',
        ):
            tx = self.service.add_transaction(
                user=self.user,
                account=self.account,
                category=self.income_category,
                amount=Decimal('100.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.INCOME,
            )
            self.service.delete_transaction(
                user=self.user,
                transaction_obj=tx,
            )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_delete_rejects_foreign_user(self) -> None:
        tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1.00'),
            date=datetime(2026, 4, 1, tzinfo=UTC),
            type=TransactionType.INCOME,
        )
        other = User.objects.create_user(
            username='x',
            password='pwd123456!',
            email='x@example.com',
        )
        with self.assertRaises(PermissionDenied):
            self.service.delete_transaction(
                user=other,
                transaction_obj=tx,
            )

    def test_copy_duplicates_transaction_and_adjusts_balance(self) -> None:
        with patch(
            'hasta_la_vista_money.transactions.services.transaction_ops.invalidate_user_detailed_statistics_cache',
        ):
            original = self.service.add_transaction(
                user=self.user,
                account=self.account,
                category=self.income_category,
                amount=Decimal('100.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.INCOME,
            )
            duplicate = self.service.copy_transaction(
                user=self.user,
                transaction_id=original.pk,
            )
        self.assertEqual(duplicate.amount, original.amount)
        self.assertNotEqual(duplicate.pk, original.pk)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1200.00'))

    def test_copy_rejects_foreign_transaction(self) -> None:
        tx = Transaction.objects.create(
            user=self.user,
            account=self.account,
            category=self.income_category,
            amount=Decimal('1.00'),
            date=datetime(2026, 4, 1, tzinfo=UTC),
            type=TransactionType.INCOME,
        )
        other = User.objects.create_user(
            username='y',
            password='pwd123456!',
            email='y@example.com',
        )
        with self.assertRaises(PermissionDenied):
            self.service.copy_transaction(
                user=other,
                transaction_id=tx.pk,
            )

    def test_update_swaps_accounts(self) -> None:
        second_account = Account.objects.get(pk=2)
        second_account.user = self.user
        second_account.balance = Decimal('500.00')
        second_account.save()

        with patch(
            'hasta_la_vista_money.transactions.services.transaction_ops.invalidate_user_detailed_statistics_cache',
        ):
            tx = self.service.add_transaction(
                user=self.user,
                account=self.account,
                category=self.expense_category,
                amount=Decimal('100.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.EXPENSE,
            )
            self.service.update_transaction(
                user=self.user,
                transaction_obj=tx,
                account=second_account,
                category=self.expense_category,
                amount=Decimal('100.00'),
                transaction_date=date(2026, 4, 1),
                type_value=TransactionType.EXPENSE,
            )

        self.account.refresh_from_db()
        second_account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(second_account.balance, Decimal('400.00'))


class CategoryServiceTest(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.service = CategoryService(
            category_repository=CategoryRepository(),
        )

    def _build_form(
        self,
        name: str,
        type_value: str,
        parent: Category | None = None,
    ) -> CategoryForm:
        form = CategoryForm(
            data={
                'name': name,
                'type': type_value,
                'parent_category': parent.pk if parent else '',
            },
            category_queryset=Category.objects.filter(
                user=self.user,
                type=type_value,
            ),
        )
        self.assertTrue(form.is_valid(), msg=form.errors)
        return form

    def test_create_category_persists_and_invalidates_cache(self) -> None:
        form = self._build_form('Аренда', TransactionType.EXPENSE)
        with (
            patch(
                'hasta_la_vista_money.transactions.services.category_ops.invalidate_user_detailed_statistics_cache',
            ) as invalidate,
            patch(
                'hasta_la_vista_money.transactions.services.category_ops.cache.delete',
            ) as cache_delete,
        ):
            created = self.service.create_category(self.user, form)
        self.assertTrue(Category.objects.filter(pk=created.pk).exists())
        invalidate.assert_called_once_with(self.user.pk)
        self.assertEqual(cache_delete.call_count, 5)

    def test_update_category_changes_name(self) -> None:
        original = Category.objects.create(
            user=self.user,
            name='Старое',
            type=TransactionType.EXPENSE,
        )
        form = self._build_form('Новое', TransactionType.EXPENSE)
        with patch(
            'hasta_la_vista_money.transactions.services.category_ops.invalidate_user_detailed_statistics_cache',
        ):
            updated = self.service.update_category(self.user, original, form)
        self.assertEqual(updated.name, 'Новое')
