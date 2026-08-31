from django.test import TestCase
from django.urls import NoReverseMatch, reverse


class ReportsRouteRemovedTest(TestCase):
    """The reports:list route was merged into users:statistics."""

    def test_reports_list_route_no_longer_resolves(self) -> None:
        with self.assertRaises(NoReverseMatch):
            reverse('reports:list')

    def test_old_reports_url_returns_404(self) -> None:
        response = self.client.get('/reports/')
        self.assertEqual(response.status_code, 404)
