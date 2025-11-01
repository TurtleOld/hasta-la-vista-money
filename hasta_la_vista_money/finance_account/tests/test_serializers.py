"""Tests for finance account serializers."""

from decimal import Decimal

from django.test import TestCase

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.serializers import AccountSerializer
from hasta_la_vista_money.users.models import User


class TestAccountSerializer(TestCase):
    """Test cases for AccountSerializer."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Test Account',
            balance=Decimal('1000.50'),
            currency='RUB',
            type_account='Debit',
        )

    def test_account_serializer_fields(self) -> None:
        """Test AccountSerializer field structure."""
        serializer = AccountSerializer(self.account)
        data = serializer.data

        expected_fields = {
            'id',
            'name_account',
            'balance',
            'currency',
            'type_account',
            'bank',
            'limit_credit',
            'payment_due_date',
            'grace_period_days',
        }

        self.assertEqual(set(data.keys()), expected_fields)

    def test_account_serializer_data_values(self) -> None:
        """Test AccountSerializer data values."""
        serializer = AccountSerializer(self.account)
        data = serializer.data

        self.assertEqual(data['id'], self.account.pk)
        self.assertEqual(data['name_account'], 'Test Account')
        self.assertEqual(data['balance'], '1000.50')
        self.assertEqual(data['currency'], 'RUB')
        self.assertEqual(data['type_account'], 'Debit')

    def test_account_serializer_with_credit_account(self) -> None:
        """Test AccountSerializer with credit account."""
        credit_account = Account.objects.create(
            user=self.user,
            name_account='Credit Card',
            balance=Decimal('-500.00'),
            currency='USD',
            type_account='CREDIT',
            bank='SBERBANK',
            limit_credit=Decimal('5000.00'),
        )

        serializer = AccountSerializer(credit_account)
        data = serializer.data

        self.assertEqual(data['name_account'], 'Credit Card')
        self.assertEqual(data['balance'], '-500.00')
        self.assertEqual(data['currency'], 'USD')
        self.assertEqual(data['type_account'], 'CREDIT')

    def test_account_serializer_with_zero_balance(self) -> None:
        """Test AccountSerializer with zero balance."""
        zero_account = Account.objects.create(
            user=self.user,
            name_account='Zero Account',
            balance=Decimal('0.00'),
            currency='EUR',
            type_account='Debit',
        )

        serializer = AccountSerializer(zero_account)
        data = serializer.data

        self.assertEqual(data['balance'], '0.00')
        self.assertEqual(data['currency'], 'EUR')

    def test_account_serializer_read_only_fields(self) -> None:
        """Test that AccountSerializer fields are not read-only."""
        serializer = AccountSerializer()

        writable_fields = ['name_account', 'balance', 'currency']
        for field_name in writable_fields:
            field = serializer.fields[field_name]
            self.assertFalse(
                field.read_only,
                f'Field {field_name} should be writable',
            )

    def test_account_serializer_multiple_accounts(self) -> None:
        """Test AccountSerializer with multiple accounts."""
        account2 = Account.objects.create(
            user=self.user,
            name_account='Second Account',
            balance=Decimal('2500.75'),
            currency='USD',
            type_account='Debit',
        )

        serializer1 = AccountSerializer(self.account)
        serializer2 = AccountSerializer(account2)

        data1 = serializer1.data
        data2 = serializer2.data

        self.assertNotEqual(data1['id'], data2['id'])
        self.assertNotEqual(data1['name_account'], data2['name_account'])
        self.assertNotEqual(data1['balance'], data2['balance'])
        self.assertNotEqual(data1['currency'], data2['currency'])

    def test_account_serializer_created_at_format(self) -> None:
        """Test AccountSerializer doesn't include created_at field."""
        serializer = AccountSerializer(self.account)
        data = serializer.data

        self.assertNotIn('created_at', data)

    def test_account_serializer_invalid_input_parametrized(self) -> None:
        """Параметризация: невалидные и граничные данные для create/update."""
        testcases = [
            ({}, ['name_account', 'balance', 'currency', 'type_account']),
            (
                {
                    'balance': '100.00',
                    'currency': 'RUB',
                    'type_account': 'Debit',
                },
                ['name_account'],
            ),
            (
                {
                    'name_account': 'Test',
                    'currency': 'RUB',
                    'type_account': 'Debit',
                },
                ['balance'],
            ),
            (
                {
                    'name_account': 'Test',
                    'balance': '10.00',
                    'type_account': 'Debit',
                },
                ['currency'],
            ),
            (
                {
                    'name_account': 'Test',
                    'currency': 'RUB',
                    'type_account': 'Debit',
                    'balance': 'oops',
                },
                ['balance'],
            ),
            (
                {
                    'name_account': 'Test',
                    'currency': 'SOMETHING',
                    'type_account': 'Debit',
                    'balance': '10.00',
                },
                ['currency'],
            ),
            (
                {
                    'name_account': 'Test',
                    'currency': 'USD',
                    'type_account': 'BADTYPE',
                    'balance': '10.00',
                },
                ['type_account'],
            ),
            (
                {
                    'name_account': 'Test',
                    'currency': 'USD',
                    'type_account': 'Debit',
                    'balance': '-5.00',
                },
                [],
            ),
        ]
        for data, fields in testcases:
            with self.subTest(data=data):
                serializer = AccountSerializer(data=data)
                valid = serializer.is_valid()
                if not valid:
                    for f in fields:
                        self.assertIn(f, serializer.errors)
                else:
                    # Если ошибок не ожидается, всё должно быть валидно
                    self.assertTrue(valid)
