from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import resolve, reverse
from hasta_la_vista_money.budget.apps import BudgetConfig
from hasta_la_vista_money.budget.models import DateList, Planning

User = get_user_model()


class BudgetConfigTest(TestCase):
    def test_app_config(self):
        self.assertEqual(BudgetConfig.name, 'hasta_la_vista_money.budget')


class BudgetModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='pass')
        self.date = date(2024, 1, 1)
        self.datelist = DateList.objects.create(user=self.user, date=self.date)
        self.planning = Planning.objects.create(
            user=self.user,
            date=self.date,
            type='expense',
            amount=100,
        )

    def test_datelist_str(self):
        self.assertEqual(str(self.datelist), f'{self.user} - {self.date}')

    def test_planning_str(self):
        self.assertIn(str(self.user), str(self.planning))
        self.assertIn(str(self.date), str(self.planning))


class BudgetUrlsTest(TestCase):
    def test_urls_resolve(self):
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
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='pass')
        self.client.force_login(self.user)
        self.date = date(2024, 1, 1)
        DateList.objects.create(user=self.user, date=self.date)

    def test_budget_view_get(self):
        response = self.client.get(reverse('budget:list'))
        self.assertIn(response.status_code, [200, 302])
        if response.status_code == 200 and response.context is not None:
            self.assertIn('chart_plan_execution_income', response.context)
            self.assertIn('chart_plan_execution_expense', response.context)

    def test_generate_date_list_view(self):
        response = self.client.post(reverse('budget:generate_date'))
        self.assertEqual(response.status_code, 302)

    def test_save_planning_post(self):
        response = self.client.post(
            reverse('budget:save_planning'),
            {'category_id': 1, 'date': self.date, 'type': 'expense', 'amount': 123},
        )
        self.assertIn(response.status_code, [200, 302, 400])

    def test_change_planning_post(self):
        response = self.client.post(
            reverse('budget:change_planning'),
            {'category_id': 1, 'date': self.date, 'type': 'expense', 'amount': 123},
        )
        self.assertIn(response.status_code, [200, 302, 400])

    def test_budget_view_no_dates(self):
        self.client.logout()
        user2 = User.objects.create_user(username='user2', password='pass')
        self.client.force_login(user2)
        response = self.client.get(reverse('budget:list'))
        self.assertIn(response.status_code, [200, 302])
        if response.status_code == 200 and response.context is not None:
            self.assertIn('chart_plan_execution_income', response.context)
