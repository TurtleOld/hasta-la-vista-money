"""Analytics currency: available set, default and remembered choice."""

from typing import TYPE_CHECKING, cast

from django.contrib.auth.models import Group
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.analytics_currency import (
    get_analytics_currency,
)
from hasta_la_vista_money.finance_account.factories import AccountFactory
from hasta_la_vista_money.finance_account.tests.helpers import (
    setup_container_for_request,
)
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.models import FamilyGroupMembership, User
from hasta_la_vista_money.users.services.groups import readable_users

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.services import (
        AnalyticsCurrencyServiceProtocol,
    )


class AnalyticsCurrencyServiceTest(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.service: AnalyticsCurrencyServiceProtocol = (
            ApplicationContainer().finance_account.analytics_currency_service()
        )

    def _available(self, *currencies: str) -> list[str]:
        for currency in currencies:
            AccountFactory(user=self.user, currency=currency)
        return self.service.available_currencies([self.user])

    def test_only_rub(self) -> None:
        available = self._available('RUB', 'RUB')

        self.assertEqual(available, ['RUB'])
        self.assertEqual(self.service.resolve(None, None, available), 'RUB')

    def test_no_accounts_falls_back_to_rub(self) -> None:
        available = self._available()

        self.assertEqual(available, [])
        self.assertEqual(self.service.resolve('USD', None, available), 'RUB')

    def test_rub_is_default_when_available(self) -> None:
        available = self._available('USD', 'RUB')

        self.assertEqual(self.service.resolve(None, None, available), 'RUB')

    def test_first_account_currency_without_rub(self) -> None:
        available = self._available('USD', 'EUR')

        self.assertEqual(available, ['USD', 'EUR'])
        self.assertEqual(self.service.resolve(None, None, available), 'USD')

    def test_request_value_wins_over_session(self) -> None:
        available = self._available('RUB', 'USD', 'EUR')

        self.assertEqual(
            self.service.resolve('EUR', 'USD', available),
            'EUR',
        )
        self.assertEqual(self.service.resolve(None, 'USD', available), 'USD')

    def test_unavailable_values_are_ignored(self) -> None:
        available = self._available('USD', 'RUB')

        self.assertEqual(self.service.resolve('JPY', 'GBP', available), 'RUB')

    def test_group_accounts_are_included(self) -> None:
        member = cast('User', UserFactory())
        group = Group.objects.create(name='Family')
        FamilyGroupMembership.objects.create(group=group, user=self.user)
        FamilyGroupMembership.objects.create(group=group, user=member)
        AccountFactory(user=self.user, currency='RUB')
        AccountFactory(user=member, currency='USD')

        self.assertEqual(
            self.service.available_currencies([self.user]),
            ['RUB'],
        )
        self.assertEqual(
            self.service.available_currencies(
                readable_users(self.user, str(group.pk)),
            ),
            ['RUB', 'USD'],
        )


SWITCHER = 'includes/analytics_currency_switcher.html'


class AnalyticsCurrencyViewHelperTest(TestCase):
    def setUp(self) -> None:
        self.user = cast('User', UserFactory())
        self.session = SessionStore()

    def _request(self, query: str = '') -> HttpRequest:
        request = RequestFactory().get(f'/analytics/{query}')
        request.user = self.user
        request.session = self.session
        setup_container_for_request(request)
        return request

    def _switcher(self, request: HttpRequest) -> str:
        return render_to_string(
            SWITCHER,
            {
                'analytics_currency': get_analytics_currency(
                    request,
                    [self.user],
                ),
            },
            request=request,
        )

    def test_single_currency_has_no_switcher(self) -> None:
        AccountFactory(user=self.user, currency='RUB')
        request = self._request()

        selected = get_analytics_currency(request, [self.user])

        self.assertEqual(selected.currency, 'RUB')
        self.assertEqual(self._switcher(request).strip(), '')

    def test_choice_is_remembered_in_session(self) -> None:
        AccountFactory(user=self.user, currency='RUB')
        AccountFactory(user=self.user, currency='USD')

        chosen = get_analytics_currency(
            self._request('?currency=USD'),
            [self.user],
        )
        later = get_analytics_currency(self._request(), [self.user])

        self.assertEqual(chosen.currency, 'USD')
        self.assertEqual(
            self.session[constants.ANALYTICS_CURRENCY_SESSION_KEY],
            'USD',
        )
        self.assertEqual(later.currency, 'USD')
        self.assertEqual(later.currencies, ['RUB', 'USD'])

    def test_unknown_currency_falls_back_to_default(self) -> None:
        AccountFactory(user=self.user, currency='USD')
        AccountFactory(user=self.user, currency='RUB')

        selected = get_analytics_currency(
            self._request('?currency=JPY'),
            [self.user],
        )

        self.assertEqual(selected.currency, 'RUB')
        self.assertNotIn(constants.ANALYTICS_CURRENCY_SESSION_KEY, self.session)

    def test_default_is_not_pinned_in_session(self) -> None:
        AccountFactory(user=self.user, currency='USD')
        get_analytics_currency(self._request(), [self.user])
        AccountFactory(user=self.user, currency='RUB')

        selected = get_analytics_currency(self._request(), [self.user])

        self.assertEqual(selected.currency, 'RUB')

    def test_session_currency_survives_narrower_scope(self) -> None:
        spouse = cast('User', UserFactory())
        AccountFactory(user=self.user, currency='RUB')
        AccountFactory(user=spouse, currency='USD')
        get_analytics_currency(
            self._request('?currency=USD'),
            [self.user, spouse],
        )

        narrow = get_analytics_currency(self._request(), [self.user])
        wide = get_analytics_currency(self._request(), [self.user, spouse])

        self.assertEqual(narrow.currency, 'RUB')
        self.assertEqual(wide.currency, 'USD')

    def test_switcher_links_keep_other_query_params(self) -> None:
        AccountFactory(user=self.user, currency='RUB')
        AccountFactory(user=self.user, currency='USD')

        html = self._switcher(self._request('?period=12m&currency=USD'))

        self.assertIn('?period=12m&amp;currency=RUB', html)
        self.assertIn('?period=12m&amp;currency=USD', html)
