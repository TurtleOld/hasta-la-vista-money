"""Tests for finance account APIs."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class TestAccountAPI(TestCase):
    """Test cases for Account API endpoints."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=Decimal('1000.00'),
            currency='RUB',
        )

    def test_account_api_list_authenticated(self) -> None:
        """Test account API list endpoint for authenticated user."""
        self.client.force_login(self.user)
        url = reverse('finance_account:api_account_list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.json())

    def test_account_api_list_unauthenticated(self) -> None:
        """Test account API list endpoint for unauthenticated user."""
        url = reverse('finance_account:api_account_list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 401)

    def test_account_api_detail_authenticated(self) -> None:
        """Test account API detail endpoint for authenticated user."""
        self.client.force_login(self.user)
        url = reverse('finance_account:api_account_detail', args=[self.account.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['name_account'], 'Test Account')
        self.assertEqual(data['balance'], '1000.00')

    def test_account_api_detail_unauthenticated(self) -> None:
        """Test account API detail endpoint for unauthenticated user."""
        url = reverse('finance_account:api_account_detail', args=[self.account.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 401)

    def test_account_api_detail_not_found(self) -> None:
        """Test account API detail endpoint with non-existent account."""
        self.client.force_login(self.user)
        url = reverse('finance_account:api_account_detail', args=[999])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_account_api_create_authenticated(self) -> None:
        """Test account API create endpoint for authenticated user."""
        self.client.force_login(self.user)
        url = reverse('finance_account:api_account_list')
        
        data = {
            'name_account': 'New Account',
            'balance': Decimal('500.00'),
            'currency': 'USD',
            'type_account': 'Debit',
        }
        
        response = self.client.post(url, data, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        
        data = response.json()
        self.assertEqual(data['name_account'], 'New Account')
        self.assertEqual(data['balance'], '500.00')

    def test_account_api_create_unauthenticated(self) -> None:
        """Test account API create endpoint for unauthenticated user."""
        url = reverse('finance_account:api_account_list')
        
        data = {
            'name_account': 'New Account',
            'balance': Decimal('500.00'),
            'currency': 'USD',
            'type_account': 'Debit',
        }
        
        response = self.client.post(url, data, content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_account_api_update_authenticated(self) -> None:
        """Test account API update endpoint for authenticated user."""
        self.client.force_login(self.user)
        url = reverse('finance_account:api_account_detail', args=[self.account.pk])
        
        data = {
            'name_account': 'Updated Account',
            'balance': Decimal('2000.00'),
            'currency': 'EUR',
            'type_account': 'Debit',
        }
        
        response = self.client.put(url, data, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(data['name_account'], 'Updated Account')
        self.assertEqual(data['balance'], '2000.00')

    def test_account_api_update_unauthenticated(self) -> None:
        """Test account API update endpoint for unauthenticated user."""
        url = reverse('finance_account:api_account_detail', args=[self.account.pk])
        
        data = {
            'name_account': 'Updated Account',
            'balance': Decimal('2000.00'),
            'currency': 'EUR',
            'type_account': 'Debit',
        }
        
        response = self.client.put(url, data, content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_account_api_delete_authenticated(self) -> None:
        """Test account API delete endpoint for authenticated user."""
        self.client.force_login(self.user)
        url = reverse('finance_account:api_account_detail', args=[self.account.pk])
        
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204)
        
        self.assertFalse(Account.objects.filter(pk=self.account.pk).exists())

    def test_account_api_delete_unauthenticated(self) -> None:
        """Test account API delete endpoint for unauthenticated user."""
        url = reverse('finance_account:api_account_detail', args=[self.account.pk])
        
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 401)

    def test_account_api_filter_by_currency(self) -> None:
        """Test account API filtering by currency."""
        Account.objects.create(
            user=self.user,
            name_account='USD Account',
            balance=Decimal('500.00'),
            currency='USD',
        )

        self.client.force_login(self.user)
        url = reverse('finance_account:api_account_list')
        response = self.client.get(url, {'currency': 'USD'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['currency'], 'USD')

    def test_account_api_filter_by_type(self) -> None:
        """Test account API filtering by account type."""
        Account.objects.create(
            user=self.user,
            name_account='Credit Account',
            balance=Decimal('0.00'),
            currency='RUB',
            type_account='CREDIT',
        )

        self.client.force_login(self.user)
        url = reverse('finance_account:api_account_list')
        response = self.client.get(url, {'type_account': 'CREDIT'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['type_account'], 'CREDIT')

    def test_account_api_pagination(self) -> None:
        """Test account API pagination."""
        for i in range(15):
            Account.objects.create(
                user=self.user,
                name_account=f'Account {i}',
                balance=Decimal('100.00'),
                currency='RUB',
            )

        self.client.force_login(self.user)
        url = reverse('finance_account:api_account_list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('count', data)
        self.assertIn('next', data)
        self.assertIn('previous', data)
        self.assertIn('results', data)
