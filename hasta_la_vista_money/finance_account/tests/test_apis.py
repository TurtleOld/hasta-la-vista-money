"""Tests for finance account APIs."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class TestAccountAPI(TestCase):
    """Test cases for Account API endpoints."""

    def setUp(self) -> None:
        """Set up test data."""
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.access_token = str(self.refresh.access_token)
        self.account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def test_account_api_list_authenticated(self) -> None:
        """Test account API list endpoint for authenticated user."""
        url = reverse('finance_account:api_list')
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_account_api_list_unauthenticated(self) -> None:
        """Test account API list endpoint for unauthenticated user."""
        url = reverse('finance_account:api_list')
        self.client.credentials()
        response = self.client.get(url)

        self.assertEqual(response.status_code, 401)

    def test_account_api_create_authenticated(self) -> None:
        """Test account API create endpoint for authenticated user."""
        url = reverse('finance_account:api_list')

        data = {
            'name_account': 'New Account',
            'balance': Decimal('500.00'),
            'currency': 'USD',
        }

        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 201)

        response_data = response.json()
        self.assertEqual(response_data['name_account'], 'New Account')
        self.assertEqual(response_data['balance'], '500.00')
        self.assertEqual(response_data['currency'], 'USD')

    def test_account_api_create_unauthenticated(self) -> None:
        """Test account API create endpoint for unauthenticated user."""
        url = reverse('finance_account:api_list')

        data = {
            'name_account': 'New Account',
            'balance': Decimal('500.00'),
            'currency': 'USD',
            'type_account': 'Debit',
        }

        self.client.credentials()
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 401)

    def test_account_api_create_invalid_data(self) -> None:
        """Test account API create with invalid data."""
        url = reverse('finance_account:api_list')

        data = {
            'name_account': '',
            'balance': Decimal('500.00'),
        }

        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_account_api_create_credit_account(self) -> None:
        """Test account API create credit account."""
        url = reverse('finance_account:api_list')

        data = {
            'name_account': 'Credit Card',
            'type_account': 'Credit',
            'bank': 'SBERBANK',
            'limit_credit': Decimal('10000.00'),
            'payment_due_date': '2024-12-31',
            'grace_period_days': 30,
            'balance': Decimal('0.00'),
            'currency': 'RUB',
        }

        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, 201)

        response_data = response.json()
        self.assertEqual(response_data['name_account'], 'Credit Card')
        self.assertEqual(response_data['type_account'], 'Credit')

    def test_account_api_filter_by_user(self) -> None:
        """Test account API filtering by user."""
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123',
        )
        Account.objects.create(
            user=other_user,
            name_account='Other Account',
            balance=Decimal('500.00'),
            currency='RUB',
        )

        url = reverse('finance_account:api_list')
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name_account'], 'Test Account')

    def test_account_api_multiple_accounts(self) -> None:
        """Test account API with multiple accounts."""
        Account.objects.create(
            user=self.user,
            name_account='Second Account',
            balance=Decimal('2000.00'),
            currency='USD',
        )

        url = reverse('finance_account:api_list')
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

    def test_account_api_content_type(self) -> None:
        """Test account API content type."""
        url = reverse('finance_account:api_list')
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_account_api_throttling(self) -> None:
        """Test account API throttling."""
        url = reverse('finance_account:api_list')
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {self.access_token}'
        )

        # Make multiple requests to test throttling
        for _ in range(5):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
