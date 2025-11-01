from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from hasta_la_vista_money.constants import RECEIPT_OPERATION_PURCHASE
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller

User = get_user_model()


class ReceiptUpdateViewTest(TestCase):
    """Тесты для проверки функциональности изменения чека
    с проверкой баланса счёта.
    """

    def setUp(self) -> None:
        """Настройка тестовых данных."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            is_active=True,
            is_superuser=True,
        )

        self.account1 = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            balance=Decimal('10000.00'),
            type_account='Debit',
            currency='RUB',
        )

        self.account2 = Account.objects.create(
            user=self.user,
            name_account='Дополнительный счёт',
            balance=Decimal('5000.00'),
            type_account='Debit',
            currency='RUB',
        )

        self.seller = Seller.objects.create(
            user=self.user,
            name_seller='Тестовый магазин',
        )

        self.product1 = Product.objects.create(
            user=self.user,
            product_name='Товар 1',
            price=Decimal('100.00'),
            quantity=Decimal('2.00'),
            amount=Decimal('200.00'),
        )

        self.product2 = Product.objects.create(
            user=self.user,
            product_name='Товар 2',
            price=Decimal('150.00'),
            quantity=Decimal('1.00'),
            amount=Decimal('150.00'),
        )

        self.receipt = Receipt.objects.create(
            user=self.user,
            seller=self.seller,
            account=self.account1,
            receipt_date='2024-01-15 12:00:00',
            number_receipt=12345,
            operation_type=RECEIPT_OPERATION_PURCHASE,
            total_sum=Decimal('350.00'),
            manual=True,
        )

        self.receipt.product.add(self.product1, self.product2)

        self.account1.balance -= self.receipt.total_sum
        self.account1.save()

        self.initial_balance = self.account1.balance

        self.client = Client()
        self.client.force_login(self.user)

    def test_receipt_update_increase_amount_same_account(self) -> None:
        """Тест увеличения суммы чека на том же счёте."""
        initial_balance = self.initial_balance

        update_data = {
            'seller': self.seller.id,
            'account': self.account1.id,
            'receipt_date': '2024-01-15 12:00:00',
            'number_receipt': 12345,
            'operation_type': 1,
            'nds10': '0.00',
            'nds20': '0.00',
            'total_sum': '500.00',
            'form-TOTAL_FORMS': '2',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-product_name': 'Товар 1',
            'form-0-price': '100.00',
            'form-0-quantity': '3.00',
            'form-0-amount': '300.00',
            'form-1-product_name': 'Товар 2',
            'form-1-price': '200.00',
            'form-1-quantity': '1.00',
            'form-1-amount': '200.00',
        }

        url = reverse('receipts:update', kwargs={'pk': self.receipt.pk})
        response = self.client.post(url, data=update_data, follow=True)

        self.assertEqual(response.status_code, 200)

        self.account1.refresh_from_db()
        self.receipt.refresh_from_db()

        expected_balance = initial_balance - Decimal('150.00')
        self.assertEqual(self.account1.balance, expected_balance)

        self.assertEqual(self.receipt.total_sum, Decimal('500.00'))

    def test_receipt_update_decrease_amount_same_account(self) -> None:
        """Тест уменьшения суммы чека на том же счёте."""
        initial_balance = self.initial_balance

        update_data = {
            'seller': self.seller.id,
            'account': self.account1.id,
            'receipt_date': '2024-01-15 12:00:00',
            'number_receipt': 12345,
            'operation_type': 1,
            'total_sum': '200.00',
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-product_name': 'Товар 1',
            'form-0-price': '100.00',
            'form-0-quantity': '2.00',
            'form-0-amount': '200.00',
        }

        response = self.client.post(
            reverse('receipts:update', kwargs={'pk': self.receipt.pk}),
            data=update_data,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.account1.refresh_from_db()
        self.receipt.refresh_from_db()

        expected_balance = initial_balance + Decimal('150.00')
        self.assertEqual(self.account1.balance, expected_balance)

        self.assertEqual(self.receipt.total_sum, Decimal('200.00'))

    def test_receipt_update_change_account(self) -> None:
        """Тест изменения счёта чека."""
        initial_balance1 = self.initial_balance
        initial_balance2 = self.account2.balance

        update_data = {
            'seller': self.seller.id,
            'account': self.account2.id,
            'receipt_date': '2024-01-15 12:00:00',
            'number_receipt': 12345,
            'operation_type': 1,
            'total_sum': '350.00',
            'form-TOTAL_FORMS': '2',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-product_name': 'Товар 1',
            'form-0-price': '100.00',
            'form-0-quantity': '2.00',
            'form-0-amount': '200.00',
            'form-1-product_name': 'Товар 2',
            'form-1-price': '150.00',
            'form-1-quantity': '1.00',
            'form-1-amount': '150.00',
        }

        response = self.client.post(
            reverse('receipts:update', kwargs={'pk': self.receipt.pk}),
            data=update_data,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.receipt.refresh_from_db()

        expected_balance1 = initial_balance1 + Decimal('350.00')
        self.assertEqual(self.account1.balance, expected_balance1)

        expected_balance2 = initial_balance2 - Decimal('350.00')
        self.assertEqual(self.account2.balance, expected_balance2)

        self.assertEqual(self.receipt.account, self.account2)

    def test_receipt_update_change_account_and_amount(self) -> None:
        """Тест изменения счёта и суммы чека одновременно."""
        initial_balance1 = self.initial_balance
        initial_balance2 = self.account2.balance

        update_data = {
            'seller': self.seller.id,
            'account': self.account2.id,
            'receipt_date': '2024-01-15 12:00:00',
            'number_receipt': 12345,
            'operation_type': 1,
            'total_sum': '500.00',
            'form-TOTAL_FORMS': '2',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-product_name': 'Товар 1',
            'form-0-price': '100.00',
            'form-0-quantity': '3.00',
            'form-0-amount': '300.00',
            'form-1-product_name': 'Товар 2',
            'form-1-price': '200.00',
            'form-1-quantity': '1.00',
            'form-1-amount': '200.00',
        }

        response = self.client.post(
            reverse('receipts:update', kwargs={'pk': self.receipt.pk}),
            data=update_data,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.account1.refresh_from_db()
        self.account2.refresh_from_db()
        self.receipt.refresh_from_db()

        expected_balance1 = initial_balance1 + Decimal('350.00')
        self.assertEqual(self.account1.balance, expected_balance1)

        expected_balance2 = initial_balance2 - Decimal('500.00')
        self.assertEqual(self.account2.balance, expected_balance2)

        self.assertEqual(self.receipt.account, self.account2)
        self.assertEqual(self.receipt.total_sum, Decimal('500.00'))

    def test_receipt_update_no_changes(self) -> None:
        """Тест обновления чека без изменений."""
        initial_balance = self.initial_balance

        update_data = {
            'seller': self.seller.id,
            'account': self.account1.id,
            'receipt_date': '2024-01-15 12:00:00',
            'number_receipt': 12345,
            'operation_type': 1,
            'total_sum': '350.00',
            'form-TOTAL_FORMS': '2',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-product_name': 'Товар 1',
            'form-0-price': '100.00',
            'form-0-quantity': '2.00',
            'form-0-amount': '200.00',
            'form-1-product_name': 'Товар 2',
            'form-1-price': '150.00',
            'form-1-quantity': '1.00',
            'form-1-amount': '150.00',
        }

        response = self.client.post(
            reverse('receipts:update', kwargs={'pk': self.receipt.pk}),
            data=update_data,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.account1.refresh_from_db()

        self.assertEqual(self.account1.balance, initial_balance)

    def test_receipt_update_unauthorized_user(self) -> None:
        """Тест попытки обновления чека неавторизованным пользователем."""
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass123',
        )

        other_receipt = Receipt.objects.create(
            user=other_user,
            seller=self.seller,
            account=self.account1,
            receipt_date='2024-01-15 12:00:00',
            number_receipt=54321,
            operation_type=RECEIPT_OPERATION_PURCHASE,
            total_sum=Decimal('100.00'),
            manual=True,
        )

        response = self.client.get(
            reverse('receipts:update', kwargs={'pk': other_receipt.pk}),
        )

        self.assertEqual(response.status_code, 404)

    def test_receipt_update_invalid_form(self) -> None:
        """Тест обновления чека с невалидными данными."""
        initial_balance = self.initial_balance

        update_data = {
            'seller': self.seller.id,
            'account': self.account1.id,
            'receipt_date': '2024-01-15 12:00:00',
            'number_receipt': 12345,
            'operation_type': 1,
            'total_sum': '100.00',
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-product_name': 'Товар 1',
            'form-0-price': 'invalid_price',
            'form-0-quantity': '1.00',
            'form-0-amount': '100.00',
        }

        response = self.client.post(
            reverse('receipts:update', kwargs={'pk': self.receipt.pk}),
            data=update_data,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.account1.refresh_from_db()

        self.assertEqual(self.account1.balance, initial_balance)

    def test_receipt_update_decimal_quantities(self) -> None:
        """Тест обновления чека с десятичными количествами."""
        initial_balance = self.initial_balance

        update_data = {
            'seller': self.seller.id,
            'account': self.account1.id,
            'receipt_date': '2024-01-15 12:00:00',
            'number_receipt': 12345,
            'operation_type': 1,
            'total_sum': '175.00',
            'form-TOTAL_FORMS': '2',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-product_name': 'Товар 1',
            'form-0-price': '100.00',
            'form-0-quantity': '0.70',
            'form-0-amount': '70.00',
            'form-1-product_name': 'Товар 2',
            'form-1-price': '150.00',
            'form-1-quantity': '0.70',
            'form-1-amount': '105.00',
        }

        response = self.client.post(
            reverse('receipts:update', kwargs={'pk': self.receipt.pk}),
            data=update_data,
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.account1.refresh_from_db()
        self.receipt.refresh_from_db()

        expected_balance = initial_balance + Decimal('175.00')
        self.assertEqual(self.account1.balance, expected_balance)

        self.assertEqual(self.receipt.total_sum, Decimal('175.00'))

        products = self.receipt.product.all()
        self.assertEqual(len(products), 2)

        product1 = products.filter(product_name='Товар 1').first()
        self.assertEqual(product1.quantity, Decimal('0.70'))
        self.assertEqual(product1.amount, Decimal('70.00'))

        product2 = products.filter(product_name='Товар 2').first()
        self.assertEqual(product2.quantity, Decimal('0.70'))
        self.assertEqual(product2.amount, Decimal('105.00'))
