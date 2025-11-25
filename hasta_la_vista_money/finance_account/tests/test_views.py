"""Tests for finance account views."""

from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase
from django.urls import reverse, reverse_lazy
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.constants import ACCOUNT_TYPE_CREDIT
from hasta_la_vista_money.finance_account.factories import AccountFactory
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.tests.helpers import (
    setup_container_for_request,
)
from hasta_la_vista_money.finance_account.views import (
    AccountCreateView,
    AccountView,
    AjaxAccountsByGroupView,
    ChangeAccountView,
    DeleteAccountView,
    TransferMoneyAccountView,
)
from hasta_la_vista_money.users.factories import UserFactory
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.users.views import AuthRequest


class TestAccountView(TestCase):
    """Test cases for AccountView."""

    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'expense.yaml',
        'expense_cat.yaml',
        'income.yaml',
        'income_cat.yaml',
    ]

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.get(id=1)
        self.factory = RequestFactory()

    def test_account_view_get_context_data(self) -> None:
        """Test AccountView get_context_data method."""
        self.client.force_login(self.user)
        url = reverse('finance_account:list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('finance_account', response.context)
        self.assertIn('add_account_form', response.context)
        self.assertIn('transfer_money_form', response.context)
        self.assertIn('transfer_money_log', response.context)
        self.assertIn('sum_all_accounts', response.context)
        self.assertIn('sum_all_accounts_in_group', response.context)

    def test_account_view_unauthenticated(self) -> None:
        """Test AccountView for unauthenticated user."""
        url = reverse('finance_account:list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, constants.REDIRECTS)

    def test_account_view_with_groups(self) -> None:
        """Test AccountView with user groups."""
        group = Group.objects.create(name='Test Group')
        self.user.groups.add(group)

        self.client.force_login(self.user)
        url = reverse('finance_account:list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('user_groups', response.context)

    def test_account_view_context_methods(self) -> None:
        """Test context data structure of AccountView."""
        view = AccountView()
        view.request = cast('AuthRequest', self.factory.get('/'))
        view.request.user = self.user
        setup_container_for_request(view.request)

        view.object_list = view.get_queryset()
        context = view.get_context_data()

        self.assertIn('accounts', context)
        self.assertIn('user_groups', context)
        self.assertIn('add_account_form', context)
        self.assertIn('transfer_money_form', context)
        self.assertIn('transfer_money_log', context)
        self.assertIn('sum_all_accounts', context)
        self.assertIn('sum_all_accounts_in_group', context)


class TestAccountCreateView(TestCase):
    """Test cases for AccountCreateView."""

    def setUp(self) -> None:
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )

    def test_account_create_view_get(self) -> None:
        """Test GET request to AccountCreateView."""
        self.client.force_login(self.user)
        url = reverse('finance_account:create')
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('add_account_form', response.context)

    def test_account_create_view_post_valid(self) -> None:
        """Test POST request with valid data."""
        self.client.force_login(self.user)
        url = reverse('finance_account:create')

        data = {
            'name_account': 'Test Account',
            'type_account': 'Debit',
            'balance': Decimal('1000.00'),
            'currency': 'RUB',
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

        account = Account.objects.filter(user=self.user).first()
        self.assertIsNotNone(account)
        assert account is not None
        self.assertEqual(account.name_account, 'Test Account')

    def test_account_create_view_post_invalid(self) -> None:
        """Test POST request with invalid data."""
        self.client.force_login(self.user)
        url = reverse('finance_account:create')

        data = {
            'name_account': '',  # Invalid empty name
            'balance': Decimal('1000.00'),
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_account_create_view_get_context_data(self) -> None:
        """Test get_context_data method."""
        view = AccountCreateView()
        view.request = cast('AuthRequest', self.factory.get('/'))
        view.request.user = self.user
        view.object = None
        setup_container_for_request(view.request)

        context = view.get_context_data()
        self.assertIn('add_account_form', context)

    def test_account_create_view_get_success_url(self) -> None:
        """Test get_success_url method."""
        view = AccountCreateView()
        url = view.get_success_url()
        self.assertEqual(url, reverse_lazy('applications:list'))


class TestChangeAccountView(TestCase):
    """Test cases for ChangeAccountView."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = cast('User', UserFactory())
        self.account = cast('Account', AccountFactory(user=self.user))
        self.factory = RequestFactory()

    def test_change_account_view_get(self) -> None:
        """Test GET request to ChangeAccountView."""
        self.client.force_login(self.user)
        url = reverse('finance_account:change', args=[self.account.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertIn('add_account_form', response.context)

    def test_change_account_view_post_valid(self) -> None:
        """Test POST request with valid data."""
        self.client.force_login(self.user)
        url = reverse('finance_account:change', args=[self.account.pk])

        data = {
            'name_account': 'Updated Account Name',
            'type_account': ACCOUNT_TYPE_CREDIT,
            'limit_credit': Decimal('1000.00'),
            'payment_due_date': timezone.now().date(),
            'grace_period_days': 30,
            'balance': Decimal('3000.00'),
            'currency': 'EUR',
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_change_account_view_get_context_data(self) -> None:
        """Test get_context_data method."""
        view = ChangeAccountView()
        view.request = cast('AuthRequest', self.factory.get('/'))
        view.request.user = self.user
        view.kwargs = {'pk': self.account.pk}
        view.object = self.account

        context = view.get_context_data()
        self.assertIn('add_account_form', context)


class TestTransferMoneyAccountView(TestCase):
    """Test cases for TransferMoneyAccountView."""

    def setUp(self) -> None:
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = cast('User', UserFactory())
        self.account1 = cast(
            'Account',
            AccountFactory(
                user=self.user,
                balance=Decimal('1000.00'),
            ),
        )
        self.account2 = cast(
            'Account',
            AccountFactory(
                user=self.user,
                balance=Decimal('500.00'),
            ),
        )

    def test_transfer_money_view_get(self) -> None:
        """Test GET request to TransferMoneyAccountView."""
        self.client.force_login(self.user)
        url = reverse('finance_account:transfer_money')
        response = self.client.get(url)

        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_transfer_money_view_post_valid(self) -> None:
        """Test POST request with valid data."""
        self.client.force_login(self.user)
        url = reverse('finance_account:transfer_money')

        initial_balance1 = self.account1.balance
        initial_balance2 = self.account2.balance
        amount = Decimal('100.00')

        data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': amount,
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }

        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

        self.account1.refresh_from_db()
        self.account2.refresh_from_db()

        self.assertEqual(self.account1.balance, initial_balance1 - amount)
        self.assertEqual(self.account2.balance, initial_balance2 + amount)

    def test_transfer_money_view_post_insufficient_funds(self) -> None:
        """Test POST request with insufficient funds."""
        self.client.force_login(self.user)
        url = reverse('finance_account:transfer_money')

        amount = self.account1.balance + Decimal('1000.00')

        data = {
            'from_account': self.account1.pk,
            'to_account': self.account2.pk,
            'amount': amount,
            'exchange_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'notes': 'Test transfer',
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_transfer_money_view_get_form_kwargs(self) -> None:
        """Test get_form_kwargs method."""
        view = TransferMoneyAccountView()
        view.request = cast('AuthRequest', self.factory.get('/'))
        view.request.user = self.user
        setup_container_for_request(view.request)

        kwargs = view.get_form_kwargs()
        self.assertIn('user', kwargs)
        self.assertEqual(kwargs['user'], self.user)


class TestDeleteAccountView(TestCase):
    """Test cases for DeleteAccountView."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = cast('User', UserFactory())
        self.account = cast('Account', AccountFactory(user=self.user))

    def test_delete_account_view_post(self) -> None:
        """Test POST request to DeleteAccountView."""
        self.client.force_login(self.user)
        url = reverse('finance_account:delete_account', args=[self.account.pk])

        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_delete_account_view_success_url(self) -> None:
        """Test success_url property."""
        view = DeleteAccountView()
        url = view.success_url
        self.assertEqual(url, reverse_lazy('finance_account:list'))


class TestAjaxAccountsByGroupView(TestCase):
    """Test cases for AjaxAccountsByGroupView."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = cast('User', UserFactory())
        self.factory = RequestFactory()

    async def test_ajax_accounts_by_group_get(self) -> None:
        """Test GET request to AjaxAccountsByGroupView."""
        view = AjaxAccountsByGroupView()
        request = self.factory.get('/?group_id=my')
        request.user = self.user
        setup_container_for_request(request)

        response = await view.get(request)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    async def test_ajax_accounts_by_group_get_with_group_id(self) -> None:
        """Test GET request with specific group_id."""
        view = AjaxAccountsByGroupView()
        request = self.factory.get('/?group_id=1')
        request.user = self.user
        setup_container_for_request(request)

        response = await view.get(request)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    async def test_ajax_accounts_by_group_get_exception(self) -> None:
        """Test GET request handling exceptions."""
        view = AjaxAccountsByGroupView()
        request = self.factory.get('/?group_id=invalid')
        request.user = self.user
        setup_container_for_request(request)

        response = await view.get(request)
        self.assertEqual(response.status_code, 500)
