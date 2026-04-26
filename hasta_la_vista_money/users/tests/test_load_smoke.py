from typing import TYPE_CHECKING

import httpx
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class CoreLoadSmokeTest(StaticLiveServerTestCase):
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

    def test_core_authenticated_endpoints_survive_http_smoke_load(
        self,
    ) -> None:
        cookies = {
            cookie_name: morsel.value
            for cookie_name, morsel in self.client.cookies.items()
        }
        urls = [
            f'{self.live_server_url}{reverse("users:dashboard_data")}',
            (
                f'{self.live_server_url}'
                f'{reverse("users:dashboard_comparison")}?period=month'
            ),
            f'{self.live_server_url}{reverse("reports:list")}',
        ]

        with httpx.Client(cookies=cookies, follow_redirects=True) as client:
            for _ in range(4):
                for url in urls:
                    response = client.get(url, timeout=10.0)
                    self.assertEqual(response.status_code, 200, msg=url)
