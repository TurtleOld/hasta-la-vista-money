"""Tests for dashboard views.

This module provides test cases for dashboard views including
authentication requirements, template rendering, and JSON responses.
"""

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
    """Test cases for DashboardView.

    Tests dashboard view authentication, template rendering, and context.
    """

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
        self.user: UserType = user
        self.client.force_login(self.user)

    def test_dashboard_view_requires_login(self) -> None:
        """Test that dashboard requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('users:dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_view_renders_template(self) -> None:
        """Test that dashboard renders correct template."""
        response = self.client.get(reverse('users:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/dashboard.html')

    def test_dashboard_view_has_context(self) -> None:
        """Test that dashboard has correct context."""
        response = self.client.get(reverse('users:dashboard'))
        self.assertIn('available_widgets', response.context)
        self.assertIn('default_period', response.context)


class DashboardDataViewTest(TestCase):
    """Test cases for DashboardDataView.

    Tests dashboard data API endpoint, authentication, and JSON responses.
    """

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
        self.user: UserType = user
        self.client.force_login(self.user)

    def test_dashboard_data_view_requires_login(self) -> None:
        """Test that dashboard API requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('users:dashboard_data'))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_data_view_returns_json(self) -> None:
        """Test that dashboard API returns JSON."""
        response = self.client.get(reverse('users:dashboard_data'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['content-type'], 'application/json')

    def test_dashboard_data_view_contains_widgets(self) -> None:
        """Test that response contains widgets."""
        response = self.client.get(reverse('users:dashboard_data'))
        data = response.json()
        self.assertIn('widgets', data)
        self.assertIsInstance(data['widgets'], list)

    def test_dashboard_data_view_contains_analytics(self) -> None:
        """Test that response contains analytics."""
        response = self.client.get(reverse('users:dashboard_data'))
        data = response.json()
        self.assertIn('analytics', data)
        self.assertIn('stats', data['analytics'])
        self.assertIn('trends', data['analytics'])

    def test_dashboard_data_view_contains_recent_transactions(self) -> None:
        """Test that response contains recent transactions."""
        response = self.client.get(reverse('users:dashboard_data'))
        data = response.json()
        self.assertIn('recent_transactions', data)
        self.assertIsInstance(data['recent_transactions'], list)

    def test_dashboard_data_view_with_period(self) -> None:
        """Test API with period parameter."""
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
    """Test cases for DashboardWidgetConfigView.

    Tests widget creation, update, deletion, and configuration.
    """

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
        self.user: UserType = user
        self.client.force_login(self.user)

    def test_create_widget(self) -> None:
        """Test widget creation."""
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
        """Test widget update."""
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
        """Test widget deletion."""
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
    """Test cases for additional analytics endpoints."""

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
        self.user: UserType = user
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
