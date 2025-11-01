from typing import ClassVar

from django.test import TestCase
from django.urls import reverse_lazy
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeViewsTest(TestCase):
    """
    Test cases for income-related views.
    """

    fixtures: ClassVar[list[str]] = [  # type: ignore[misc]
        'users.yaml',
        'finance_account.yaml',
        'income.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.income = Income.objects.get(pk=1)
        self.income_type = IncomeCategory.objects.get(pk=1)
        self.parent_category = IncomeCategory.objects.get(name='Зарплата')

    def test_list_income(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('income:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_create(self) -> None:
        self.client.force_login(self.user)
        url = reverse_lazy('income:create')
        new_income = {
            'user': self.user.pk,
            'account': self.account.pk,
            'category': self.income_type.pk,
            'date': '2023-12-20 15:30',
            'amount': 15000,
        }
        response = self.client.post(url, data=new_income, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_update(self) -> None:
        self.client.force_login(self.user)
        url = reverse_lazy('income:change', args=(self.income.pk,))
        update_income = {
            'category': self.income_type.pk,
            'account': self.account.pk,
            'date': '2023-06-30T22:31',
            'amount': 25000,
        }
        response = self.client.post(url, update_income)
        self.assertEqual(response.status_code, constants.REDIRECTS)
        updated_income = Income.objects.get(pk=self.income.pk)
        self.assertEqual(updated_income.amount, 25000)

    def test_income_delete(self) -> None:
        self.client.force_login(self.user)
        url = reverse_lazy('income:delete_income', args=(self.income.pk,))
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_copy_view(self) -> None:
        self.client.force_login(self.user)
        response = self.client.post(
            reverse_lazy('income:income_copy', args=[self.income.pk]),
        )
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_update_view_get(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(
            reverse_lazy('income:change', args=[self.income.pk]),
        )
        self.assertEqual(response.status_code, 200)

    def test_income_update_view_post(self) -> None:
        self.client.force_login(self.user)
        data = {
            'category': self.income_type.pk,
            'account': self.account.pk,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'amount': 2000,
        }
        response = self.client.post(
            reverse_lazy('income:change', args=[self.income.pk]),
            data,
        )
        self.assertEqual(response.status_code, 302)

    def test_income_delete_view(self) -> None:
        self.client.force_login(self.user)
        response = self.client.post(
            reverse_lazy('income:delete_income', args=[self.income.pk]),
        )
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_category_view(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('income:category_list'))
        self.assertEqual(response.status_code, 200)

    def test_income_category_create_view_get(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('income:create_category'))
        self.assertEqual(response.status_code, 200)

    def test_income_category_create_view_post(self) -> None:
        self.client.force_login(self.user)
        data = {
            'name': 'New Test Category',
            'parent_category': self.parent_category.pk,
        }
        response = self.client.post(
            reverse_lazy('income:create_category'),
            data,
        )
        self.assertEqual(response.status_code, 302)

    def test_income_category_create_view_invalid_form(self) -> None:
        self.client.force_login(self.user)
        data = {
            'name': '',
            'parent_category': self.parent_category.pk,
        }
        response = self.client.post(
            reverse_lazy('income:create_category'),
            data,
        )
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_category_delete_view(self) -> None:
        self.client.force_login(self.user)
        response = self.client.post(
            reverse_lazy(
                'income:delete_category_income',
                args=[self.income_type.pk],
            ),
        )
        self.assertEqual(response.status_code, 302)

    def test_income_view_unauthenticated(self) -> None:
        response = self.client.get(reverse_lazy('income:list'))
        self.assertEqual(response.status_code, 302)

    def test_income_create_view_unauthenticated(self) -> None:
        response = self.client.get(reverse_lazy('income:create'))
        self.assertEqual(response.status_code, 302)

    def test_income_update_view_unauthenticated(self) -> None:
        response = self.client.get(
            reverse_lazy('income:change', args=[self.income.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_income_delete_view_unauthenticated(self) -> None:
        response = self.client.post(
            reverse_lazy('income:delete_income', args=[self.income.pk]),
        )
        self.assertEqual(response.status_code, constants.REDIRECTS)

    def test_income_category_view_unauthenticated(self) -> None:
        response = self.client.get(reverse_lazy('income:category_list'))
        self.assertEqual(response.status_code, 302)

    def test_income_category_create_view_unauthenticated(self) -> None:
        response = self.client.get(reverse_lazy('income:create_category'))
        self.assertEqual(response.status_code, constants.REDIRECTS)

    def test_income_category_delete_view_unauthenticated(self) -> None:
        response = self.client.post(
            reverse_lazy(
                'income:delete_category_income',
                args=[self.income_type.pk],
            ),
        )
        self.assertEqual(response.status_code, 302)
