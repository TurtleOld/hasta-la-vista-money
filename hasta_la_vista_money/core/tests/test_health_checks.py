from http import HTTPStatus

from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_healthz_returns_ok(self) -> None:
        response = self.client.get(reverse('healthz'))

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {'status': 'ok'}

    def test_readyz_returns_dependency_status(self) -> None:
        response = self.client.get(reverse('readyz'))

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            'status': 'ok',
            'checks': {
                'database': True,
                'cache': True,
            },
        }
