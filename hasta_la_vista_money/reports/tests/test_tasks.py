"""Tests for reports Celery tasks."""

import inspect

from django.test import TestCase

from hasta_la_vista_money.reports.tasks import (
    generate_monthly_report,
    generate_user_statistics,
    generate_yearly_report,
)
from hasta_la_vista_money.users.models import User


class ReportTaskTests(TestCase):
    """Reports tasks should be regular Celery tasks."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='reports-user',
            password='pass',  # nosec B106: test-only password
        )

    def test_report_generators_are_celery_tasks(self) -> None:
        """Expose Celery task API instead of coroutine functions."""
        for task in (
            generate_monthly_report,
            generate_yearly_report,
            generate_user_statistics,
        ):
            self.assertTrue(hasattr(task, 'delay'))
            self.assertFalse(inspect.iscoroutinefunction(task.run))

    def test_generate_monthly_report_returns_success(self) -> None:
        """Generate an empty monthly report synchronously via task run."""
        result = generate_monthly_report.run(self.user.pk, 2026, 1)

        self.assertTrue(result['success'])
        self.assertEqual(result['report']['period']['year'], 2026)
        self.assertEqual(result['report']['period']['month'], 1)

    def test_generate_yearly_report_returns_success(self) -> None:
        """Generate an empty yearly report synchronously via task run."""
        result = generate_yearly_report.run(self.user.pk, 2026)

        self.assertTrue(result['success'])
        self.assertEqual(result['report']['year'], 2026)

    def test_generate_user_statistics_returns_success(self) -> None:
        """Generate empty user statistics synchronously via task run."""
        result = generate_user_statistics.run(self.user.pk)

        self.assertTrue(result['success'])
        self.assertEqual(result['statistics']['user_id'], self.user.pk)
