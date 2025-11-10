"""Тесты для views дашборда."""

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money.users.models import DashboardWidget

User = get_user_model()

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()


class DashboardViewTest(TestCase):
    """Тесты для DashboardView."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
    ]

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg = 'No user found in fixtures'
            raise ValueError(msg)
        self.user: UserType = user
        self.client.force_login(self.user)

    def test_dashboard_view_requires_login(self) -> None:
        """Тест, что дашборд требует авторизации."""
        self.client.logout()
        response = self.client.get(reverse('users:dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_view_renders_template(self) -> None:
        """Тест, что дашборд рендерит правильный шаблон."""
        response = self.client.get(reverse('users:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/dashboard.html')

    def test_dashboard_view_has_context(self) -> None:
        """Тест, что дашборд имеет правильный контекст."""
        response = self.client.get(reverse('users:dashboard'))
        self.assertIn('available_widgets', response.context)
        self.assertIn('default_period', response.context)


class DashboardDataViewTest(TestCase):
    """Тесты для DashboardDataView."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'expense_cat.yaml',
        'expense.yaml',
        'income_cat.yaml',
        'income.yaml',
    ]

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg = 'No user found in fixtures'
            raise ValueError(msg)
        self.user: UserType = user
        self.client.force_login(self.user)

    def test_dashboard_data_view_requires_login(self) -> None:
        """Тест, что API дашборда требует авторизации."""
        self.client.logout()
        response = self.client.get(reverse('users:dashboard_data'))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_data_view_returns_json(self) -> None:
        """Тест, что API возвращает JSON."""
        response = self.client.get(reverse('users:dashboard_data'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['content-type'], 'application/json')

    def test_dashboard_data_view_contains_widgets(self) -> None:
        """Тест, что ответ содержит виджеты."""
        response = self.client.get(reverse('users:dashboard_data'))
        data = response.json()
        self.assertIn('widgets', data)
        self.assertIsInstance(data['widgets'], list)

    def test_dashboard_data_view_contains_analytics(self) -> None:
        """Тест, что ответ содержит аналитику."""
        response = self.client.get(reverse('users:dashboard_data'))
        data = response.json()
        self.assertIn('analytics', data)
        self.assertIn('stats', data['analytics'])
        self.assertIn('trends', data['analytics'])

    def test_dashboard_data_view_contains_recent_transactions(self) -> None:
        """Тест, что ответ содержит последние операции."""
        response = self.client.get(reverse('users:dashboard_data'))
        data = response.json()
        self.assertIn('recent_transactions', data)
        self.assertIsInstance(data['recent_transactions'], list)

    def test_dashboard_data_view_with_period(self) -> None:
        """Тест API с указанием периода."""
        response = self.client.get(
            reverse('users:dashboard_data'),
            {'period': 'quarter'},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('comparison', data)


class DashboardWidgetConfigViewTest(TestCase):
    """Тесты для DashboardWidgetConfigView."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
    ]

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg = 'No user found in fixtures'
            raise ValueError(msg)
        self.user: UserType = user
        self.client.force_login(self.user)

    def test_create_widget(self) -> None:
        """Тест создания виджета."""
        response = self.client.post(
            reverse('users:dashboard_widget'),
            data={
                'widget_type': 'balance',
                'position': 0,
                'width': 6,
                'height': 300,
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        widget = DashboardWidget.objects.filter(user=self.user).first()
        self.assertIsNotNone(widget)
        assert widget is not None
        self.assertEqual(widget.widget_type, 'balance')

    def test_update_widget(self) -> None:
        """Тест обновления виджета."""
        widget = DashboardWidget.objects.create(
            user=self.user,
            widget_type='balance',
            position=0,
            width=6,
            height=300,
        )

        response = self.client.post(
            reverse('users:dashboard_widget'),
            data={
                'widget_id': widget.pk,
                'position': 1,
                'width': 12,
                'height': 400,
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        widget.refresh_from_db()
        self.assertEqual(widget.position, 1)
        self.assertEqual(widget.width, 12)
        self.assertEqual(widget.height, 400)

    def test_delete_widget(self) -> None:
        """Тест удаления виджета."""
        widget = DashboardWidget.objects.create(
            user=self.user,
            widget_type='balance',
            position=0,
        )

        response = self.client.post(
            reverse('users:dashboard_widget'),
            data={
                'widget_id': widget.pk,
                'action': 'delete',
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            DashboardWidget.objects.filter(pk=widget.pk).exists(),
        )
