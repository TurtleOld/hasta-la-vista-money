from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from config.settings.debug_toolbar.setup import DebugToolbarSetup, show_toolbar


class ShowToolbarTest(SimpleTestCase):
    def test_show_toolbar_disabled_flag(self) -> None:
        with (
            patch('config.settings.debug_toolbar.settings.DEBUG_TOOLBAR_ENABLED', False),
            patch('config.settings.debug_toolbar.setup.debug_toolbar', object()),
        ):
            self.assertFalse(show_toolbar())

    def test_show_toolbar_missing_package(self) -> None:
        with (
            patch('config.settings.debug_toolbar.settings.DEBUG_TOOLBAR_ENABLED', True),
            patch('config.settings.debug_toolbar.setup.debug_toolbar', None),
            patch('config.settings.debug_toolbar.setup.logger'),
        ):
            self.assertFalse(show_toolbar())

    def test_show_toolbar_enabled(self) -> None:
        with (
            patch('config.settings.debug_toolbar.settings.DEBUG_TOOLBAR_ENABLED', True),
            patch('config.settings.debug_toolbar.setup.debug_toolbar', object()),
        ):
            self.assertTrue(show_toolbar())


class DebugToolbarSetupTest(SimpleTestCase):
    def test_do_settings_no_toolbar(self) -> None:
        with patch('config.settings.debug_toolbar.setup.show_toolbar', return_value=False):
            apps, middleware = DebugToolbarSetup.do_settings(['django.contrib.admin'], ['django.middleware.security.SecurityMiddleware'])
            self.assertEqual(apps, ['django.contrib.admin'])
            self.assertEqual(middleware, ['django.middleware.security.SecurityMiddleware'])

    def test_do_settings_append_middleware(self) -> None:
        with patch('config.settings.debug_toolbar.setup.show_toolbar', return_value=True):
            apps, middleware = DebugToolbarSetup.do_settings(['app'], ['mw'])
            self.assertEqual(apps[-1], 'debug_toolbar')
            self.assertEqual(middleware[-1], 'debug_toolbar.middleware.DebugToolbarMiddleware')

    def test_do_settings_insert_middleware(self) -> None:
        with patch('config.settings.debug_toolbar.setup.show_toolbar', return_value=True):
            apps, middleware = DebugToolbarSetup.do_settings(['app'], ['mw1', 'mw2'], middleware_position=1)
            self.assertEqual(apps[-1], 'debug_toolbar')
            self.assertEqual(middleware[1], 'debug_toolbar.middleware.DebugToolbarMiddleware')

    def test_do_urls_without_toolbar(self) -> None:
        with patch('config.settings.debug_toolbar.setup.show_toolbar', return_value=False):
            urlpatterns = [1, 2, 3]
            self.assertEqual(DebugToolbarSetup.do_urls(urlpatterns), urlpatterns)

    def test_do_urls_with_toolbar(self) -> None:
        fake_toolbar = SimpleNamespace(urls=['pattern'])
        with (
            patch('config.settings.debug_toolbar.setup.show_toolbar', return_value=True),
            patch('config.settings.debug_toolbar.setup.debug_toolbar', fake_toolbar),
        ):
            urlpatterns = [1]
            result = DebugToolbarSetup.do_urls(urlpatterns)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0], 1)

