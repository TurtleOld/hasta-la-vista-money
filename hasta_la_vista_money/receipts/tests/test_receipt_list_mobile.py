from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money import constants


class ReceiptListMobileActionsTests(TestCase):
    def setUp(self) -> None:
        user = get_user_model().objects.create_user(
            username='receipts-mobile-user',
            password='test-pass-123',
        )
        self.client.force_login(user)

    def test_mobile_scan_action_points_to_scanner(self) -> None:
        response = self.client.get(reverse('receipts:list'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(response, 'data-scan-action', count=1)
        self.assertContains(
            response,
            f'{reverse("receipts:upload")}?mode=scan',
        )
        self.assertContains(response, 'Сканировать QR')

    def test_more_menu_collects_secondary_actions(self) -> None:
        response = self.client.get(reverse('receipts:list'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(response, 'data-receipts-more-link', count=4)
        for url in (
            reverse('receipts:category_twins'),
            reverse('users:statistics'),
            reverse('receipts:products'),
            reverse('receipts:create_seller'),
        ):
            self.assertContains(response, f'href="{url}"')

    def test_more_menu_is_native_disclosure(self) -> None:
        response = self.client.get(reverse('receipts:list'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(response, '<details class="receipts-menu">')
        self.assertContains(
            response,
            'aria-label="Дополнительные действия"',
        )

    def test_desktop_actions_are_kept(self) -> None:
        response = self.client.get(reverse('receipts:list'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(
            response,
            'class="receipts-actions receipts-actions-desktop"',
        )
        self.assertContains(response, f'href="{reverse("receipts:create")}"')
        self.assertContains(
            response,
            f'href="{reverse("receipts:category_twins")}"',
        )
        self.assertContains(response, f'href="{reverse("users:statistics")}"')
