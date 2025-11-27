"""Тесты для views дашборда."""

import json
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.test_helpers import setup_container_for_request
from hasta_la_vista_money.users.models import DashboardWidget
from hasta_la_vista_money.users.views import (
    DashboardComparisonView,
    DashboardDataView,
    DashboardDrillDownView,
)

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
        self.assertIsInstance(user, User)
        self.user: User = user
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
        self.assertIsInstance(user, User)
        self.user: User = user
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

    def test_dashboard_data_view_requires_authentication(self) -> None:
        request = RequestFactory().get(reverse('users:dashboard_data'))
        request.user = AnonymousUser()
        setup_container_for_request(request)
        response = DashboardDataView().get(request)  # type: ignore[arg-type]
        payload = json.loads(response.content.decode())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(payload, {'error': 'User not authenticated'})

    @patch('hasta_la_vista_money.users.views.get_user_detailed_statistics')
    def test_dashboard_data_view_handles_error(
        self,
        mock_stats: Any,
    ) -> None:
        mock_stats.side_effect = ValueError('boom')
        request = RequestFactory().get(reverse('users:dashboard_data'))
        request.user = self.user
        setup_container_for_request(request)
        with patch('hasta_la_vista_money.users.views.cache.delete'):
            response = DashboardDataView().get(request)  # type: ignore[arg-type]
        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.content.decode())
        self.assertIn('error', payload)
        self.assertIn('traceback', payload)


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
        self.assertIsInstance(user, User)
        self.user: User = user
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
        widget = cast('DashboardWidget', widget)
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


class DashboardAnalyticsEndpointsTest(TestCase):
    """Тесты для дополнительных аналитических эндпоинтов."""

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
        self.assertIsInstance(user, User)
        self.user: User = user
        self.client.force_login(self.user)
        self.factory = RequestFactory()

    @patch('hasta_la_vista_money.users.views.get_drill_down_data')
    def test_dashboard_drilldown_returns_data(self, mock_drill: Any) -> None:
        mock_drill.return_value = {'items': [1, 2]}
        response = self.client.get(
            reverse('users:dashboard_drilldown'),
            {
                'category_id': '5',
                'date': '2025-01-01',
                'type': 'income',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'items': [1, 2]})
        mock_drill.assert_called_once_with(
            user=self.user,
            category_id='5',
            date_str='2025-01-01',
            data_type='income',
        )

    def test_dashboard_drilldown_requires_authentication(self) -> None:
        request = self.factory.get(reverse('users:dashboard_drilldown'))
        request.user = AnonymousUser()
        setup_container_for_request(request)
        response = DashboardDrillDownView().get(request)
        payload = json.loads(response.content.decode())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(payload, {'error': 'User not authenticated'})

    @patch('hasta_la_vista_money.users.views.get_period_comparison')
    def test_dashboard_comparison_returns_data(
        self,
        mock_comparison: Any,
    ) -> None:
        mock_comparison.return_value = {'result': 'ok'}
        response = self.client.get(
            reverse('users:dashboard_comparison'),
            {'period': 'quarter'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'result': 'ok'})
        mock_comparison.assert_called_once_with(
            user=self.user,
            period_type='quarter',
        )

    def test_dashboard_comparison_requires_authentication(self) -> None:
        request = self.factory.get(reverse('users:dashboard_comparison'))
        request.user = AnonymousUser()
        setup_container_for_request(request)
        response = DashboardComparisonView().get(request)
        payload = json.loads(response.content.decode())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(payload, {'error': 'User not authenticated'})
