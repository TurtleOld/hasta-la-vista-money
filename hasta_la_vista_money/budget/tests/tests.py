from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import resolve, reverse

from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.apps import BudgetConfig
from hasta_la_vista_money.budget.models import DateList, Planning

User = get_user_model()


class BudgetConfigTest(TestCase):
    def test_app_config(self) -> None:
        self.assertEqual(BudgetConfig.name, 'hasta_la_vista_money.budget')


class BudgetModelTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='testuser',
            password='pass',
        )
        self.date = date(2024, 1, 1)
        self.datelist = DateList.objects.create(user=self.user, date=self.date)
        self.planning = Planning.objects.create(
            user=self.user,
            date=self.date,
            planning_type='expense',
            amount=100,
        )

    def test_datelist_str(self) -> None:
        self.assertEqual(str(self.datelist), f'{self.user} - {self.date}')

    def test_planning_str(self) -> None:
        self.assertIn(str(self.user), str(self.planning))
        self.assertIn(str(self.date), str(self.planning))


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


class BudgetViewsTest(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='pass',
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
        from hasta_la_vista_money.expense.models import ExpenseCategory

        category = ExpenseCategory.objects.create(
            user=self.user,
            name='Test Category',
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
            password='pass',
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
