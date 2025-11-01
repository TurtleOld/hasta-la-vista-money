from typing import ClassVar

from django.test import TestCase
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.forms import AddCategoryIncomeForm, IncomeForm
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeFormTest(TestCase):
    """
    Test cases for the IncomeForm.
    """

    fixtures: ClassVar[list[str]] = [
        'users.yaml',
        'finance_account.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.income_type = IncomeCategory.objects.get(pk=1)

    def test_income_form_validation(self) -> None:
        income_categories = IncomeCategory.objects.filter(user=self.user)
        form = IncomeForm(
            data={
                'category': self.income_type.pk,
                'account': self.account.pk,
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'amount': 1000,
            },
            category_queryset=income_categories,
            account_queryset=Account.objects.filter(user=self.user),
        )
        self.assertTrue(form.is_valid())

    def test_income_form_invalid(self) -> None:
        income_categories = IncomeCategory.objects.filter(user=self.user)
        form = IncomeForm(
            data={
                'category': self.income_type.pk,
                'amount': 'invalid_amount',
            },
            category_queryset=income_categories,
            account_queryset=Account.objects.filter(user=self.user),
        )
        self.assertFalse(form.is_valid())

    def test_income_form_field_configuration(self) -> None:
        form = IncomeForm(
            category_queryset=IncomeCategory.objects.filter(user=self.user),
            account_queryset=Account.objects.filter(user=self.user),
        )
        self.assertIn('category', form.fields)
        self.assertIn('account', form.fields)
        self.assertIn('date', form.fields)
        self.assertIn('amount', form.fields)

    def test_income_form_configure_category_choices(self) -> None:
        form = IncomeForm(
            category_queryset=IncomeCategory.objects.filter(user=self.user),
            account_queryset=Account.objects.filter(user=self.user),
        )
        category_choices = [('1', 'Category 1'), ('2', 'Category 2')]
        form.configure_category_choices(category_choices)
        self.assertEqual(form.fields['category'].choices, category_choices)


class AddCategoryIncomeFormTest(TestCase):
    """
    Test cases for the AddCategoryIncomeForm.
    """

    fixtures: ClassVar[list[str]] = ['users.yaml', 'income_cat.yaml']

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.parent_category = IncomeCategory.objects.get(name='Зарплата')
        self.income_type = IncomeCategory.objects.get(pk=1)

    def test_create_category_income_form_validation(self) -> None:
        income_categories = IncomeCategory.objects.filter(user=self.user)
        form = AddCategoryIncomeForm(
            data={
                'name': 'Test Category',
                'parent_category': self.parent_category.pk,
            },
            category_queryset=income_categories,
        )
        self.assertTrue(form.is_valid())

    def test_create_category_income_form_invalid(self) -> None:
        form = AddCategoryIncomeForm(
            data={
                'name': '',
            },
        )
        self.assertFalse(form.is_valid())

    def test_create_category_income_form_field_configuration(self) -> None:
        form = AddCategoryIncomeForm(
            category_queryset=IncomeCategory.objects.filter(user=self.user),
        )
        self.assertIn('name', form.fields)
        self.assertIn('parent_category', form.fields)

    def test_create_category_income_form_configure_category_choices(
        self,
    ) -> None:
        form = AddCategoryIncomeForm(
            category_queryset=IncomeCategory.objects.filter(user=self.user),
        )
        category_choices = [('1', 'Category 1'), ('2', 'Category 2')]
        form.configure_category_choices(category_choices)
        self.assertEqual(
            form.fields['parent_category'].choices,
            category_choices,
        )
