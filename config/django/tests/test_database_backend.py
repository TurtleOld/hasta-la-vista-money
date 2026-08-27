from django.conf import settings
from django.test import SimpleTestCase


class TestDatabaseBackendTest(SimpleTestCase):
    def test_tests_use_postgresql_backend(self) -> None:
        self.assertEqual(
            settings.DATABASES['default']['ENGINE'],
            'django.db.backends.postgresql',
        )
