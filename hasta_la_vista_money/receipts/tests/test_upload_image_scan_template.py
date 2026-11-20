"""Layout contract for the camera-first QR scan panel."""

from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.typing_helpers import get_user_model


class UploadImageScanTemplateTests(TestCase):
    def setUp(self) -> None:
        user = get_user_model().objects.create_user(
            username='scan-template-user',
            password='test-pass-123',
        )
        Account.objects.create(
            user=user,
            name_account='РосДорБанк ···0281',
        )
        self.client.force_login(user)
        self.url = reverse('receipts:upload')

    def _scan_html(self) -> str:
        response = self.client.get(self.url, {'mode': 'scan'})
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        return response.content.decode()

    def test_camera_stage_carries_real_camera_flow(self) -> None:
        html = self._scan_html()

        self.assertIn('class="receipts-scan-stage"', html)
        self.assertIn('x-ref="video"', html)
        self.assertIn('data-worker-url=', html)
        self.assertIn('data-wasm-url=', html)
        self.assertIn('data-upload-url=', html)
        self.assertIn('data-scan-url=', html)
        self.assertIn('data-notifications-url=', html)
        self.assertIn('x-ref="photoInput"', html)
        self.assertIn('capture="environment"', html)
        self.assertIn('name="csrfmiddlewaretoken"', html)

    def test_account_selector_and_torch_live_in_camera_chrome(self) -> None:
        html = self._scan_html()

        scan_form = html[html.index('id="scanQrForm"') :]
        self.assertIn('receipts-scan-chrome', scan_form)
        self.assertIn('receipts-scan-account', scan_form)
        self.assertIn('receipts-scan-account-select', scan_form)
        self.assertIn('Счёт для нового чека', scan_form)
        self.assertIn('name="account"', scan_form)
        self.assertIn('toggleTorch()', scan_form)
        self.assertIn('aria-label="Фонарик"', scan_form)
        self.assertIn('x-bind:aria-pressed="torchEnabled"', scan_form)
        self.assertLess(
            scan_form.index('receipts-scan-chrome'),
            scan_form.index('name="account"'),
        )
        self.assertLess(
            scan_form.index('name="account"'),
            scan_form.index('receipts-scan-frame'),
        )

    def test_viewfinder_has_corner_frame_and_single_hint_line(self) -> None:
        html = self._scan_html()

        self.assertIn('receipts-scan-frame', html)
        for corner in ('tl', 'tr', 'bl', 'br'):
            self.assertIn(f'class="{corner}"', html)
        self.assertIn('x-text="hintText"', html)
        self.assertIn('x-text="statusMessage"', html)
        self.assertIn('role="status"', html)
        self.assertIn('aria-live="polite"', html)

    def test_notice_is_a_dismissible_success_toast(self) -> None:
        html = self._scan_html()

        self.assertIn('class="receipts-scan-notice"', html)
        self.assertIn('x-show="noticeMessage"', html)
        self.assertIn('x-text="noticeMessage"', html)
        self.assertIn('x-bind:href="noticeLink"', html)
        self.assertIn('x-on:click="dismissNotice()"', html)
        self.assertEqual(html.count('x-on:click="dismissNotice()"'), 2)
        self.assertIn('aria-label="Закрыть уведомление"', html)
        self.assertIn('Открыть чек', html)
        self.assertNotIn('Открыть проведённый чек', html)
        self.assertNotIn(
            'class="receipts-upload-error" x-show="noticeMessage"',
            html,
        )
        self.assertEqual(
            html.count(
                'receipts-button receipts-button-primary receipts-scan-done',
            ),
            1,
        )

    def test_actions_expose_file_photo_and_done(self) -> None:
        html = self._scan_html()

        self.assertIn('receipts-scan-actions', html)
        self.assertIn('x-on:click="selectFile()"', html)
        self.assertIn('x-on:click="takePhoto()"', html)
        self.assertIn('aria-label="Сделать фото"', html)
        self.assertIn(
            'class="receipts-button receipts-button-primary '
            'receipts-scan-done"',
            html,
        )
        self.assertIn('x-text="sentCount"', html)
        self.assertIn('Готово', html)

    def test_camera_errors_keep_their_own_slot(self) -> None:
        html = self._scan_html()

        self.assertIn('id="scan-error"', html)
        self.assertIn('x-text="errorMessage"', html)
        self.assertIn('role="alert"', html)

    def test_no_mock_or_demo_controls_reach_production(self) -> None:
        html = self._scan_html()

        for marker in ('demoShow', 'demoReset', 'demo-btn', 'макет'):
            self.assertNotIn(marker, html)

    def test_file_mode_keeps_tabs_and_the_same_scan_panel(self) -> None:
        response = self.client.get(self.url)
        html = response.content.decode()

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertNotIn('is-scan-mode', html)
        self.assertIn('receipts-mode-tabs', html)
        self.assertIn('receipts-scan-notice', html)
        self.assertIn('receipts-scan-stage', html)
