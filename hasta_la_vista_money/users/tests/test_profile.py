from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.forms import UpdateUserForm
from hasta_la_vista_money.users.services.profile import update_user_profile

if TYPE_CHECKING:
    from hasta_la_vista_money.users.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class UpdateUserProfileServiceTest(TestCase):
    """Tests for update_user_profile service function."""

    fixtures = ['users.yaml']

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.assertIsInstance(user, User)
        self.user: UserType = user

    def test_update_user_profile(self) -> None:
        form: UpdateUserForm = UpdateUserForm(
            instance=self.user,
            data={
                'username': self.user.username,
                'email': 'newemail@example.com',
                'first_name': 'NewName',
                'last_name': self.user.last_name,
                'timezone_name': self.user.timezone_name,
            },
        )
        self.assertTrue(form.is_valid())
        user: UserType = update_user_profile(form)
        self.assertEqual(user.email, 'newemail@example.com')
        self.assertEqual(user.first_name, 'NewName')

    def test_update_user_profile_rejects_unknown_timezone(self) -> None:
        form: UpdateUserForm = UpdateUserForm(
            instance=self.user,
            data={
                'username': self.user.username,
                'email': self.user.email or 'user@example.com',
                'first_name': self.user.first_name,
                'last_name': self.user.last_name,
                'timezone_name': 'Not/AZone',
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn('timezone_name', form.errors)

    def test_existing_user_defaults_to_europe_moscow(self) -> None:
        self.assertEqual(self.user.timezone_name, 'Europe/Moscow')


class ProfileTimezoneUiTest(TestCase):
    """Tests for the timezone field in the profile UI."""

    fixtures = ['users.yaml']

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.user: UserType = user

    def test_profile_page_offers_full_iana_timezone_list(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('users:profile', kwargs={'pk': self.user.pk}),
        )

        self.assertContains(response, 'id="timezone-list"')
        self.assertContains(response, 'list="timezone-list"')
        self.assertContains(response, 'Asia/Tokyo')
        self.assertContains(response, 'Europe/Moscow')

    def test_ajax_save_accepts_valid_timezone(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('users:update_user', kwargs={'pk': self.user.pk}),
            {
                'username': self.user.username,
                'email': self.user.email or 'user@example.com',
                'first_name': self.user.first_name,
                'last_name': self.user.last_name,
                'timezone_name': 'Asia/Tokyo',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.timezone_name, 'Asia/Tokyo')

    def test_ajax_save_rejects_unknown_timezone(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('users:update_user', kwargs={'pk': self.user.pk}),
            {
                'username': self.user.username,
                'email': self.user.email or 'user@example.com',
                'first_name': self.user.first_name,
                'last_name': self.user.last_name,
                'timezone_name': 'Not/AZone',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertIn('timezone_name', payload['errors'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.timezone_name, 'Europe/Moscow')


class ProfileTimezoneAffectsLocalDateTest(TestCase):
    """The saved timezone must apply to the very next request."""

    fixtures = ['users.yaml']

    def setUp(self) -> None:
        user = User.objects.first()
        if user is None:
            msg: str = 'No user found in fixtures'
            raise ValueError(msg)
        self.user: UserType = user
        self.account = Account.objects.create(
            user=self.user,
            name_account='Card',
            balance=Decimal('1000.00'),
            currency='RUB',
        )
        self.category = Category.objects.create(
            user=self.user,
            name='Food',
            type=TransactionType.EXPENSE,
        )
        # 2026-03-10 20:00 UTC is still 2026-03-10 in Europe/Moscow (+3,
        # 23:00) but already 2026-03-11 in Asia/Tokyo (+9, 05:00).
        self.moment = datetime(2026, 3, 10, 20, 0, tzinfo=UTC)
        self.transaction = Transaction.objects.create(
            type=TransactionType.EXPENSE,
            user=self.user,
            account=self.account,
            category=self.category,
            amount=Decimal('42.00'),
            date=self.moment,
        )
        self.client.force_login(self.user)

    def _includes_transaction(self, local_day: str) -> bool:
        response = self.client.get(
            reverse('finances'),
            {'date_from': local_day, 'date_to': local_day},
            HTTP_HX_REQUEST='true',
        )
        marker = reverse(
            'finance_account:transaction_change',
            kwargs={'pk': self.transaction.pk},
        )
        return marker in response.content.decode()

    def test_new_timezone_applies_right_after_profile_save(self) -> None:
        self.assertFalse(self._includes_transaction('2026-03-11'))

        response = self.client.post(
            reverse('users:update_user', kwargs={'pk': self.user.pk}),
            {
                'username': self.user.username,
                'email': self.user.email or 'user@example.com',
                'first_name': self.user.first_name,
                'last_name': self.user.last_name,
                'timezone_name': 'Asia/Tokyo',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertTrue(response.json()['success'])

        self.assertTrue(self._includes_transaction('2026-03-11'))

    def test_timezone_change_does_not_rewrite_saved_timestamps(self) -> None:
        self.client.post(
            reverse('users:update_user', kwargs={'pk': self.user.pk}),
            {
                'username': self.user.username,
                'email': self.user.email or 'user@example.com',
                'first_name': self.user.first_name,
                'last_name': self.user.last_name,
                'timezone_name': 'Asia/Tokyo',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.date, self.moment)
