from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import resolve, reverse

from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.apps import BudgetConfig
from hasta_la_vista_money.budget.models import Budget, DateList, Planning
from hasta_la_vista_money.budget.presentation import build_budget_matrix_context
from hasta_la_vista_money.transactions.models import Category, TransactionType
from hasta_la_vista_money.users.models import FamilyGroupMembership

User = get_user_model()


class BudgetConfigTest(TestCase):
    def test_app_config(self) -> None:
        self.assertEqual(BudgetConfig.name, 'hasta_la_vista_money.budget')


class BudgetModelTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='testuser',
            password='pass',  # nosec B106: test-only password
        )
        self.date = date(2024, 1, 1)
        self.datelist = DateList.objects.create(user=self.user, date=self.date)
        self.category = Category.objects.create(
            user=self.user,
            name='Test Category',
            type=TransactionType.EXPENSE,
        )
        self.planning = Planning.objects.create(
            user=self.user,
            date=self.date,
            planning_type=TransactionType.EXPENSE,
            category=self.category,
            amount=100,
        )
        self.budget = Budget.objects.create(
            user=self.user,
            period=self.date,
            category=self.category,
            amount_limit=500,
            alert_threshold=75,
        )

    def test_datelist_str(self) -> None:
        self.assertEqual(str(self.datelist), f'{self.user} - {self.date}')

    def test_planning_str(self) -> None:
        self.assertIn(str(self.user), str(self.planning))
        self.assertIn(str(self.date), str(self.planning))

    def test_budget_str(self) -> None:
        self.assertIn(str(self.user), str(self.budget))
        self.assertIn(str(self.date), str(self.budget))


class BudgetUrlsTest(TestCase):
    def test_urls_resolve(self) -> None:
        self.assertEqual(resolve('/budget/').view_name, 'budget:list')
        self.assertEqual(
            resolve('/budget/generate-date/').view_name,
            'budget:generate_date',
        )
        self.assertEqual(
            resolve('/budget/change-planning/').view_name,
            'budget:change_planning',
        )
        self.assertEqual(
            resolve('/budget/save-planning/').view_name,
            'budget:save_planning',
        )
        self.assertEqual(
            resolve('/budget/save-limit/').view_name,
            'budget:save_limit',
        )


class BudgetPresentationTest(TestCase):
    def test_budget_matrix_defaults_to_current_month_window(self) -> None:
        months = [
            date(2025, 11, 1),
            date(2025, 12, 1),
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
            date(2026, 4, 1),
            date(2026, 5, 1),
            date(2026, 6, 1),
            date(2026, 7, 1),
            date(2026, 8, 1),
            date(2026, 9, 1),
            date(2026, 10, 1),
        ]

        context = build_budget_matrix_context(
            table_type=TransactionType.EXPENSE,
            months=months,
            rows=[],
            total_fact=[0] * len(months),
            total_plan=[0] * len(months),
            current_date=date(2026, 5, 26),
        )

        self.assertEqual(context['budget_visible_start'], constants.SIX)
        self.assertEqual(context['budget_visible_default'], constants.SIX)
        self.assertEqual(context['budget_visible_range'], '6')
        self.assertEqual(context['budget_months'][0], date(2025, 11, 1))
        self.assertFalse(
            context['budget_month_columns'][5]['is_visible_default']
        )
        self.assertTrue(
            context['budget_month_columns'][6]['is_visible_default']
        )

    def test_budget_matrix_all_range_shows_history(self) -> None:
        months = [
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
        ]

        context = build_budget_matrix_context(
            table_type=TransactionType.EXPENSE,
            months=months,
            rows=[],
            total_fact=[0] * len(months),
            total_plan=[0] * len(months),
            current_date=date(2026, 3, 26),
            selected_range='all',
        )

        self.assertEqual(context['budget_visible_start'], constants.ZERO)
        self.assertEqual(context['budget_visible_default'], len(months))
        self.assertEqual(context['budget_visible_range'], 'all')
        self.assertTrue(
            all(
                column['is_visible_default']
                for column in context['budget_month_columns']
            ),
        )


class BudgetViewsTest(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='pass',  # nosec B106: test-only password
        )
        self.client.force_login(self.user)
        self.date = date(2024, 1, 1)
        DateList.objects.create(user=self.user, date=self.date)

    def test_budget_view_get(self) -> None:
        response = self.client.get(reverse('budget:list'))
        self.assertIn(response.status_code, [200, 302])
        if (
            response.status_code == constants.SUCCESS_CODE
            and response.context is not None
        ):
            self.assertIn('chart_data', response.context)
            chart_data = response.context['chart_data']
            self.assertIn('chart_plan_execution_income', chart_data)
            self.assertIn('chart_plan_execution_expense', chart_data)

    def test_budget_view_renders_family_scope_choice(self) -> None:
        response = self.client.get(reverse('budget:list'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(response, 'Семья')
        self.assertContains(response, '?scope=family')

    def test_expense_table_range_buttons_render(self) -> None:
        Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )

        response = self.client.get(reverse('budget:expense_table'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(
            response,
            'hx-get="/budget/expenses/?scope=my&range=6"',
        )
        self.assertContains(
            response,
            'hx-get="/budget/expenses/?scope=my&range=all"',
        )

    def test_expense_table_hx_range_all_marks_all_active(self) -> None:
        Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )

        response = self.client.get(
            f'{reverse("budget:expense_table")}?range=all',
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(response, 'data-budget-range="all"', count=0)
        self.assertContains(response, 'range=all')

    def test_generate_date_list_view(self) -> None:
        response = self.client.post(
            reverse('budget:generate_date'),
            {'type': 'expense'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('success', response.json())
        self.assertIn('redirect_url', response.json())

    def test_save_planning_post(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Test Category',
            type=TransactionType.EXPENSE,
        )
        response = self.client.post(
            reverse('budget:save_planning'),
            {
                'category_id': category.id,
                'month': self.date.isoformat(),
                'type': 'expense',
                'amount': 123,
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('success', response.json())
        self.assertIn('amount', response.json())

    def test_save_planning_family_scope_uses_category_owner(self) -> None:
        member = User.objects.create_user(
            username='family-member',
            password='pass',  # nosec B106: test-only password
        )
        group = Group.objects.create(name='Budget family')
        FamilyGroupMembership.objects.create(
            group=group,
            user=self.user,
            role=FamilyGroupMembership.Role.OWNER,
        )
        FamilyGroupMembership.objects.create(group=group, user=member)
        category = Category.objects.create(
            user=member,
            name='Shared food',
            type=TransactionType.EXPENSE,
        )

        response = self.client.post(
            reverse('budget:save_planning'),
            {
                'category_id': category.id,
                'month': self.date.isoformat(),
                'type': TransactionType.EXPENSE,
                'amount': 321,
                'scope': 'family',
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertTrue(
            Planning.objects.filter(
                user=member,
                category=category,
                amount=321,
            ).exists(),
        )

    def test_save_budget_limit_post(self) -> None:
        category = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        response = self.client.post(
            reverse('budget:save_limit'),
            {
                'category_id': category.id,
                'month': self.date.isoformat(),
                'amount_limit': 1000,
                'alert_threshold': 85,
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('success', response.json())
        self.assertEqual(
            Budget.objects.get(category=category).alert_threshold,
            85,
        )

    def test_save_overall_budget_limit_htmx_uses_month_start(self) -> None:
        self.user.budget_date_lists.all().delete()
        DateList.objects.create(user=self.user, date=date(2024, 5, 24))

        response = self.client.post(
            reverse('budget:save_limit'),
            {
                'category_id': '',
                'month': '2024-05-24',
                'amount_limit': 2000,
                'alert_threshold': 80,
            },
            HTTP_HX_REQUEST='true',
        )

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertTrue(
            Budget.objects.filter(
                user=self.user,
                category__isnull=True,
                period=date(2024, 5, 1),
                amount_limit=2000,
            ).exists(),
        )
        self.assertContains(response, 'value="2000,00"')

    def test_change_planning_post(self) -> None:
        response = self.client.post(
            reverse('budget:change_planning'),
            {'planning': 100},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('planning_value', response.json())

    def test_budget_view_no_dates(self) -> None:
        self.client.logout()
        user2 = User.objects.create_user(
            username='user2',
            password='pass',  # nosec B106: test-only password
        )
        self.client.force_login(user2)
        response = self.client.get(reverse('budget:list'))
        self.assertIn(response.status_code, [200, 302])
        if (
            response.status_code == constants.SUCCESS_CODE
            and response.context is not None
        ):
            self.assertIn('chart_data', response.context)
            chart_data = response.context['chart_data']
            self.assertIn('chart_plan_execution_income', chart_data)
