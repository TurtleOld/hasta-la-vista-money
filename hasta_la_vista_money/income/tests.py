from decimal import Decimal

from django.test import TestCase
from django.urls import reverse_lazy
from django.utils import timezone
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.filters import IncomeFilter
from hasta_la_vista_money.income.forms import AddCategoryIncomeForm, IncomeForm
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User

TEST_AMOUNT = 15000
NEW_TEST_AMOUNT = 25000


class TestIncome(TestCase):
    """Test cases for Income application."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'income.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.income = Income.objects.get(pk=1)
        self.income_type = IncomeCategory.objects.get(pk=1)
        self.parent_category = IncomeCategory.objects.get(name='Зарплата')

    def test_list_income(self):
        """Test income list view."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('income:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_create(self):
        """Test income creation."""
        self.client.force_login(self.user)

        url = reverse_lazy('income:create')

        new_income = {
            'user': self.user.pk,
            'account': self.account.pk,
            'category': self.income_type.pk,
            'date': '2023-12-20 15:30',
            'amount': TEST_AMOUNT,
        }

        # Get the category queryset for the user
        income_categories = (
            IncomeCategory.objects.filter(user=self.user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

        form = IncomeForm(
            data=new_income,
            user=self.user,
            depth=3,
            category_queryset=income_categories,
        )
        self.assertTrue(form.is_valid())

        response = self.client.post(url, data=new_income, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_update(self):
        """Test income update."""
        self.client.force_login(self.user)
        url = reverse_lazy('income:change', args=(self.income.pk,))

        # Отладочная информация
        print(f'Test user: {self.user} (pk={self.user.pk})')
        print(
            f'Test income_type: {self.income_type} (pk={self.income_type.pk}, user={self.income_type.user})',
        )
        print(
            f'Test income: {self.income} (pk={self.income.pk}, user={self.income.user})',
        )

        update_income = {
            'category': self.income_type.pk,
            'account': self.account.pk,
            'date': '2023-06-30T22:31',
            'amount': NEW_TEST_AMOUNT,
        }

        # Get the category queryset for the user
        income_categories = (
            IncomeCategory.objects.filter(user=self.user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

        print(f'Available categories for user: {[cat.pk for cat in income_categories]}')

        form = IncomeForm(
            data=update_income,
            user=self.user,
            depth=3,
            category_queryset=income_categories,
        )
        self.assertTrue(form.is_valid())

        response = self.client.post(url, update_income)
        if response.status_code != constants.REDIRECTS:
            # Попробуем вывести ошибки формы из контекста ответа
            form_in_context = (
                response.context.get('form')
                if hasattr(response, 'context') and response.context
                else None
            )
            if form_in_context is not None:
                print('Form errors:', form_in_context.errors)
                print('Non-field errors:', form_in_context.non_field_errors())
            else:
                print('No form in response context. Response content:')
                print(response.content.decode())
        self.assertEqual(response.status_code, constants.REDIRECTS)

        updated_income = Income.objects.get(pk=self.income.pk)
        self.assertEqual(updated_income.amount, NEW_TEST_AMOUNT)

    def test_income_delete(self):
        """Test income deletion."""
        self.client.force_login(self.user)

        url = reverse_lazy('income:delete_income', args=(self.income.pk,))

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_category_income_create(self):
        """Test income category creation."""
        self.client.force_login(self.user)

        new_category = {
            'name': 'Вторая часть',
            'parent_category': self.parent_category.pk,
        }

        income_categories = (
            IncomeCategory.objects.filter(user=self.user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

        form = AddCategoryIncomeForm(
            data=new_category,
            user=self.user,
            depth=3,
            category_queryset=income_categories,
        )
        self.assertTrue(form.is_valid())

    def test_category_income_delete(self):
        """Test income category deletion."""
        self.client.force_login(self.user)

        url = reverse_lazy(
            'income:delete_category_income',
            args=(self.income.pk,),
        )

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_income_model_str(self):
        """Test Income model string representation."""
        self.assertEqual(str(self.income), str(self.income.category))

    def test_income_category_model_str(self):
        """Test IncomeCategory model string representation."""
        self.assertEqual(str(self.income_type), self.income_type.name)

    def test_income_form_validation(self):
        """Test IncomeForm validation."""
        # Get the category queryset for the user
        income_categories = (
            IncomeCategory.objects.filter(user=self.user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

        form = IncomeForm(
            data={
                'category': self.income_type.pk,
                'account': self.account.pk,
                'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
                'amount': 1000,
            },
            user=self.user,
            depth=3,
            category_queryset=income_categories,
        )
        self.assertTrue(form.is_valid())

    def test_income_form_invalid(self):
        """Test IncomeForm with invalid data."""
        # Get the category queryset for the user
        income_categories = (
            IncomeCategory.objects.filter(user=self.user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

        form = IncomeForm(
            data={
                'category': self.income_type.pk,
                'amount': 'invalid_amount',
            },
            user=self.user,
            depth=3,
            category_queryset=income_categories,
        )
        self.assertFalse(form.is_valid())

    def test_create_category_income_form_validation(self):
        """Test AddCategoryIncomeForm validation."""
        # Get the category queryset for the user
        income_categories = (
            IncomeCategory.objects.filter(user=self.user)
            .select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

        form = AddCategoryIncomeForm(
            data={
                'name': 'Test Category',
                'parent_category': self.parent_category.pk,
            },
            user=self.user,
            depth=3,
            category_queryset=income_categories,
        )
        self.assertTrue(form.is_valid())

    def test_create_category_income_form_invalid(self):
        """Test AddCategoryIncomeForm with invalid data."""
        form = AddCategoryIncomeForm(
            data={
                'name': '',
            },
            user=self.user,
            depth=3,
        )
        self.assertFalse(form.is_valid())

    def test_income_filter(self):
        """Test IncomeFilter functionality."""
        filter_instance = IncomeFilter(
            data={},
            queryset=Income.objects.all(),
            user=self.user,
        )
        self.assertIsNotNone(filter_instance.qs)

    def test_income_filter_with_data(self):
        """Test IncomeFilter with filter data."""
        filter_instance = IncomeFilter(
            data={
                'category': self.income_type.pk,
                'account': self.account.pk,
            },
            queryset=Income.objects.all(),
            user=self.user,
        )
        self.assertIsNotNone(filter_instance.qs)

    def test_income_view_context_data(self):
        """Test IncomeView context data."""
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('income:list'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('categories', response.context)
        self.assertIn('income_filter', response.context)
        self.assertIn('income_by_month', response.context)
        self.assertIn('income_form', response.context)
        self.assertIn('flattened_categories', response.context)

    def test_income_create_view_form_valid(self):
        """Test IncomeCreateView form validation."""
        self.client.force_login(self.user)

        data = {
            'category': self.income_type.pk,
            'account': self.account.pk,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'amount': 1000,
        }

        response = self.client.post(reverse_lazy('income:create'), data)
        self.assertEqual(response.status_code, 200)

    def test_income_copy_view(self):
        """Test IncomeCopyView functionality."""
        self.client.force_login(self.user)

        response = self.client.post(
            reverse_lazy('income:income_copy', args=[self.income.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_income_update_view_get(self):
        """Test IncomeUpdateView GET request."""
        self.client.force_login(self.user)

        response = self.client.get(reverse_lazy('income:change', args=[self.income.pk]))
        self.assertEqual(response.status_code, 200)

    def test_income_update_view_post(self):
        """Test IncomeUpdateView POST request."""
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

    def test_income_delete_view(self):
        """Test IncomeDeleteView functionality."""
        self.client.force_login(self.user)

        response = self.client.post(
            reverse_lazy('income:delete_income', args=[self.income.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_income_category_view(self):
        """Test IncomeCategoryView functionality."""
        self.client.force_login(self.user)

        response = self.client.get(reverse_lazy('income:category_list'))
        self.assertEqual(response.status_code, 200)

    def test_income_category_create_view_get(self):
        """Test IncomeCategoryCreateView GET request."""
        self.client.force_login(self.user)

        response = self.client.get(reverse_lazy('income:create_category'))
        self.assertEqual(response.status_code, 200)

    def test_income_category_create_view_post(self):
        """Test IncomeCategoryCreateView POST request."""
        self.client.force_login(self.user)

        data = {
            'name': 'New Test Category',
            'parent_category': self.parent_category.pk,
        }

        response = self.client.post(reverse_lazy('income:create_category'), data)
        self.assertEqual(response.status_code, 302)

    def test_income_category_create_view_invalid_form(self):
        """Test IncomeCategoryCreateView with invalid form."""
        self.client.force_login(self.user)

        data = {
            'name': '',
            'parent_category': self.parent_category.pk,
        }

        response = self.client.post(reverse_lazy('income:create_category'), data)
        self.assertEqual(response.status_code, 302)

    def test_income_category_delete_view(self):
        """Test IncomeCategoryDeleteView functionality."""
        self.client.force_login(self.user)

        response = self.client.post(
            reverse_lazy('income:delete_category_income', args=[self.income_type.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_income_form_configure_category_choices(self):
        """Test IncomeForm configure_category_choices method."""
        form = IncomeForm(user=self.user, depth=3)
        category_choices = [('1', 'Category 1'), ('2', 'Category 2')]
        form.configure_category_choices(category_choices)
        self.assertEqual(form.fields['category'].choices, category_choices)

    def test_create_category_income_form_configure_category_choices(self):
        """Test AddCategoryIncomeForm configure_category_choices method."""
        form = AddCategoryIncomeForm(user=self.user, depth=3)
        category_choices = [('1', 'Category 1'), ('2', 'Category 2')]
        form.configure_category_choices(category_choices)
        self.assertEqual(form.fields['parent_category'].choices, category_choices)

    def test_income_model_meta(self):
        """Test Income model Meta configuration."""
        self.assertEqual(Income._meta.model_name, 'income')
        self.assertEqual(Income._meta.app_label, 'income')

    def test_income_category_model_meta(self):
        """Test IncomeCategory model Meta configuration."""
        self.assertEqual(IncomeCategory._meta.model_name, 'incomecategory')
        self.assertEqual(IncomeCategory._meta.app_label, 'income')
        self.assertEqual(IncomeCategory._meta.ordering, ['parent_category_id'])

    def test_income_category_without_parent(self):
        """Test IncomeCategory without parent category."""
        category = IncomeCategory.objects.create(
            user=self.user,
            name='Test Category Without Parent',
        )
        self.assertIsNone(category.parent_category)

    def test_income_category_with_parent(self):
        """Test IncomeCategory with parent category."""
        child_category = IncomeCategory.objects.create(
            user=self.user,
            name='Child Category',
            parent_category=self.parent_category,
        )
        self.assertEqual(child_category.parent_category, self.parent_category)

    def test_income_filter_property_qs(self):
        """Test IncomeFilter qs property."""
        filter_instance = IncomeFilter(
            data={},
            queryset=Income.objects.all(),
            user=self.user,
        )
        queryset = filter_instance.qs
        self.assertIsNotNone(queryset)
        self.assertTrue(hasattr(queryset, 'values'))

    def test_income_view_unauthenticated(self):
        """Test IncomeView for unauthenticated user."""
        response = self.client.get(reverse_lazy('income:list'))
        self.assertEqual(response.status_code, 302)

    def test_income_create_view_unauthenticated(self):
        """Test IncomeCreateView for unauthenticated user."""
        response = self.client.get(reverse_lazy('income:create'))
        self.assertEqual(response.status_code, 302)

    def test_income_update_view_unauthenticated(self):
        """Test IncomeUpdateView for unauthenticated user."""
        response = self.client.get(reverse_lazy('income:change', args=[self.income.pk]))
        self.assertEqual(response.status_code, 302)

    def test_income_delete_view_unauthenticated(self):
        """Test IncomeDeleteView for unauthenticated user."""
        response = self.client.post(
            reverse_lazy('income:delete_income', args=[self.income.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_income_category_view_unauthenticated(self):
        """Test IncomeCategoryView for unauthenticated user."""
        response = self.client.get(reverse_lazy('income:category_list'))
        self.assertEqual(response.status_code, 302)

    def test_income_category_create_view_unauthenticated(self):
        """Test IncomeCategoryCreateView for unauthenticated user."""
        response = self.client.get(reverse_lazy('income:create_category'))
        self.assertEqual(response.status_code, constants.REDIRECTS)

    def test_income_category_delete_view_unauthenticated(self):
        """Test IncomeCategoryDeleteView for unauthenticated user."""
        response = self.client.post(
            reverse_lazy('income:delete_category_income', args=[self.income_type.pk]),
        )
        self.assertEqual(response.status_code, 302)

    def test_income_form_field_configuration(self):
        """Test IncomeForm field configuration."""
        form = IncomeForm(user=self.user, depth=3)
        self.assertIn('category', form.fields)
        self.assertIn('account', form.fields)
        self.assertIn('date', form.fields)
        self.assertIn('amount', form.fields)

    def test_create_category_income_form_field_configuration(self):
        """Test AddCategoryIncomeForm field configuration."""
        form = AddCategoryIncomeForm(user=self.user, depth=3)
        self.assertIn('name', form.fields)
        self.assertIn('parent_category', form.fields)

    def test_income_filter_init(self):
        """Test IncomeFilter initialization."""
        filter_instance = IncomeFilter(
            data={},
            queryset=Income.objects.all(),
            user=self.user,
        )
        self.assertEqual(filter_instance.user, self.user)

    def test_income_model_created_at(self):
        """Test Income model created_at field."""
        income = Income.objects.create(
            user=self.user,
            account=self.account,
            category=self.income_type,
            date=timezone.now(),
            amount=Decimal('1000.00'),
        )
        self.assertIsNotNone(income.created_at)
