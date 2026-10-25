from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money import constants

SCANNER_LINK = 'href="/receipts/upload/?mode=scan" aria-current="page"'
RECEIPTS_LINK = 'href="/receipts/" aria-current="page"'


class BottomNavScannerTests(TestCase):
    def setUp(self) -> None:
        user = get_user_model().objects.create_user(
            username='nav-user',
            password='test-pass-123',
        )
        self.client.force_login(user)

    def test_upload_page_highlights_scanner_only(self) -> None:
        response = self.client.get(reverse('receipts:upload'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(response, SCANNER_LINK, count=1)
        self.assertNotContains(response, RECEIPTS_LINK)

    def test_receipts_list_highlights_receipts_only(self) -> None:
        response = self.client.get(reverse('receipts:list'))

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertContains(response, RECEIPTS_LINK, count=1)
        self.assertNotContains(response, SCANNER_LINK)

    def test_statistics_stays_in_mobile_menu_only(self) -> None:
        response = self.client.get(reverse('receipts:list'))

        self.assertContains(
            response,
            f'href="{reverse("users:statistics")}" data-mobile-menu-link',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("users:statistics")}" class="flex min-w-',
        )
