"""Tests for category CRUD HTML views."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User

TEST_PASSWORD = 'pwd123456!'  # nosec B105


class CategoryCRUDViewsTest(TestCase):
    fixtures: ClassVar[list[str]] = ['users.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.user.set_password(TEST_PASSWORD)
        self.user.save()
        self.client.login(username=self.user.username, password=TEST_PASSWORD)

    def test_list_view_redirects_to_finances_categories(self) -> None:
        response = self.client.get(reverse('transactions:category_list'))
        self.assertRedirects(
            response,
            reverse('finances_categories'),
            fetch_redirect_response=False,
        )

    def test_create_get_renders_form_with_expense_default(self) -> None:
        response = self.client.get(reverse('transactions:create_category'))
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertEqual(form.initial['type'], TransactionType.EXPENSE)

    def test_create_get_with_income_query_param(self) -> None:
        response = self.client.get(
            reverse('transactions:create_category') + '?type=income',
        )
        form = response.context['form']
        self.assertEqual(form.initial['type'], TransactionType.INCOME)

    def test_create_post_persists_category(self) -> None:
        response = self.client.post(
            reverse('transactions:create_category') + '?type=expense',
            data={'name': 'Транспорт', 'type': 'expense'},
        )
        self.assertRedirects(
            response,
            reverse('finances_categories'),
            fetch_redirect_response=False,
        )
        self.assertTrue(
            Category.objects.filter(
                user=self.user,
                name='Транспорт',
                type='expense',
            ).exists(),
        )

    def test_update_post_changes_name(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Старое',
            type=TransactionType.EXPENSE,
        )
        response = self.client.post(
            reverse('transactions:update_category', args=[category.pk]),
            data={'name': 'Новое', 'type': 'expense'},
        )
        self.assertRedirects(
            response,
            reverse('finances_categories'),
            fetch_redirect_response=False,
        )
        category.refresh_from_db()
        self.assertEqual(category.name, 'Новое')

    def test_update_rejects_foreign_category(self) -> None:
        other = User.objects.create_user(
            username='other',
            password=TEST_PASSWORD,
            email='o@example.com',
        )
        category = Category.objects.create(
            user=other,
            name='Чужая',
            type=TransactionType.EXPENSE,
        )
        response = self.client.post(
            reverse('transactions:update_category', args=[category.pk]),
            data={'name': 'X', 'type': 'expense'},
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_removes_category(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Удалить',
            type=TransactionType.EXPENSE,
        )
        response = self.client.post(
            reverse('transactions:delete_category', args=[category.pk]),
        )
        self.assertRedirects(
            response,
            reverse('finances_categories'),
            fetch_redirect_response=False,
        )
        self.assertFalse(Category.objects.filter(pk=category.pk).exists())

    def test_delete_protected_category_shows_error(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Защита',
            type=TransactionType.EXPENSE,
        )
        account = Account.objects.create(
            user=self.user,
            name_account='Тест',
            balance=Decimal('100.00'),
            currency='RUB',
            type_account='D',
        )
        Transaction.objects.create(
            user=self.user,
            account=account,
            category=category,
            amount=Decimal('1.00'),
            date=datetime(2026, 5, 1, tzinfo=UTC),
            type=TransactionType.EXPENSE,
        )
        response = self.client.post(
            reverse('transactions:delete_category', args=[category.pk]),
        )
        self.assertRedirects(
            response,
            reverse('finances_categories'),
            fetch_redirect_response=False,
        )
        self.assertTrue(Category.objects.filter(pk=category.pk).exists())

    def test_anonymous_user_redirected_to_login(self) -> None:
        self.client.logout()
        response = self.client.get(reverse('transactions:create_category'))
        self.assertEqual(response.status_code, 302)
