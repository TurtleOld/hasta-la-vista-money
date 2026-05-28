from http import HTTPStatus
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money import __version__
from hasta_la_vista_money.system.services.pwa import get_pwa_precache_payload


class PwaManifestTests(TestCase):
    def test_manifest_is_available(self) -> None:
        manifest_path = (
            Path(settings.BASE_DIR) / 'static' / 'manifest.webmanifest'
        )
        self.assertTrue(manifest_path.is_file())

        response = self.client.get('/static/manifest.webmanifest')

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertIn('application/manifest+json', response['Content-Type'])
        content = b''.join(response.streaming_content)
        self.assertIn(b'"name": "Hasta La Vista, Money!"', content)
        self.assertIn(b'"display": "standalone"', content)

    def test_base_template_includes_manifest_link(self) -> None:
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username='pwa-user',
            password='test-pass-123',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('finances'))

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertContains(response, 'rel="manifest"')
        self.assertContains(response, 'apple-touch-icon')
        self.assertContains(response, 'name="theme-color"')


class ServiceWorkerTests(TestCase):
    def test_service_worker_is_available(self) -> None:
        response = self.client.get(reverse('service_worker'))

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertEqual(response['Content-Type'], 'application/javascript')
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertIn('must-revalidate', response['Cache-Control'])
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertIn(b"addEventListener('install'", response.content)

    def test_precache_payload_contains_core_assets(self) -> None:
        payload = get_pwa_precache_payload()

        self.assertEqual(payload['version'], __version__)
        self.assertEqual(payload['offline_url'], reverse('offline'))
        self.assertIn('/static/css/styles.min.css', payload['precache'])
        self.assertIn('/static/js/dist/app.js', payload['precache'])

    def test_precache_endpoint_returns_json(self) -> None:
        response = self.client.get(reverse('service_worker_precache'))

        self.assertEqual(response.status_code, HTTPStatus.OK)
        data = response.json()
        self.assertEqual(data['version'], __version__)
        self.assertIn('/offline/', data['precache'])

    def test_offline_page_is_available(self) -> None:
        response = self.client.get(reverse('offline'))

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertContains(response, 'Нет подключения к интернету')

    def test_app_bundle_registers_service_worker(self) -> None:
        sw_path = Path(settings.BASE_DIR) / 'static' / 'js' / 'dist' / 'app.js'
        content = sw_path.read_text(encoding='utf-8')

        self.assertIn('serviceWorker.register("/sw.js"', content)
