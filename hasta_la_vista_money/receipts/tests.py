import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse_lazy
from django.utils import timezone
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.forms import (
    ProductForm,
    ProductFormSet,
    ReceiptFilter,
    ReceiptForm,
    SellerForm,
    UploadImageForm,
)
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.services import (
    analyze_image_with_ai,
    image_to_base64,
)
from hasta_la_vista_money.users.models import User
from rest_framework import status
from rest_framework.test import APITestCase


class TestReceipt(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_receipt.yaml',
        'receipt_seller.yaml',
        'receipt_product.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.user2 = User.objects.get(pk=2)
        self.account = Account.objects.get(pk=1)
        self.receipt = Receipt.objects.get(pk=1)
        self.seller = Seller.objects.get(pk=1)
        self.product = Product.objects.get(pk=1)

    def test_receipt_list(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('receipts:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_receipt_create(self):
        self.client.force_login(self.user)
        url = reverse_lazy('receipts:create')

        new_seller_data = {
            'user': self.user,
            'name_seller': 'ООО Рога и Копыта',
        }
        new_seller = Seller.objects.create(**new_seller_data)

        form_data = {
            'seller': new_seller.id,
            'account': self.account.id,
            'receipt_date': '2023-06-28 21:24',
            'number_receipt': 111,
            'operation_type': 1,
            'total_sum': 10,
            'form-TOTAL_FORMS': 1,
            'form-INITIAL_FORMS': 0,
            'form-MIN_NUM_FORMS': 0,
            'form-MAX_NUM_FORMS': 1000,
            'form-0-product_name': 'Яблоко',
            'form-0-price': 10,
            'form-0-quantity': 1,
            'form-0-amount': 10,
            'form-0-nds_type': 1,
            'form-0-nds_sum': 1.3,
        }

        response = self.client.post(url, data=form_data)
        self.assertEqual(response.status_code, constants.REDIRECTS)

    def test_receipt_delete(self):
        self.client.force_login(self.user)
        url = reverse_lazy('receipts:delete', kwargs={'pk': self.receipt.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, constants.REDIRECTS)

    def test_receipt_list_unauthorized(self):
        response = self.client.get(reverse_lazy('receipts:list'))
        self.assertRedirects(response, '/login/?next=/receipts/')

    def test_receipt_create_unauthorized(self):
        response = self.client.get(reverse_lazy('receipts:create'))
        self.assertRedirects(response, '/login/?next=/receipts/create/')

    def test_receipt_delete_unauthorized(self):
        response = self.client.get(
            reverse_lazy('receipts:delete', kwargs={'pk': self.receipt.pk}),
        )
        self.assertRedirects(response, '/login/?next=/receipts/1/')


class TestSeller(TestCase):
    fixtures = [
        'users.yaml',
        'receipt_seller.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)

    def test_seller_creation(self):
        seller_data = {
            'name_seller': 'Тестовый магазин',
            'retail_place_address': 'ул. Тестовая, 1',
            'retail_place': 'Магазин "Тест"',
        }
        seller = Seller.objects.create(user=self.user, **seller_data)
        self.assertEqual(seller.name_seller, 'Тестовый магазин')
        self.assertEqual(seller.user, self.user)

    def test_seller_str_representation(self):
        seller = Seller.objects.create(user=self.user, name_seller='Тестовый продавец')
        self.assertEqual(str(seller), 'Тестовый продавец')

    def test_seller_create_view(self):
        self.client.force_login(self.user)
        url = reverse_lazy('receipts:create_seller')

        data = {
            'name_seller': 'Новый продавец',
            'retail_place_address': 'ул. Новая, 2',
            'retail_place': 'Магазин "Новый"',
        }

        response = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)

        seller = Seller.objects.filter(name_seller='Новый продавец').first()
        self.assertIsNotNone(seller)
        if seller:
            self.assertEqual(seller.user, self.user)


class TestProduct(TestCase):
    fixtures = [
        'users.yaml',
        'receipt_product.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)

    def test_product_creation(self):
        product_data = {
            'user': self.user,
            'product_name': 'Тестовый продукт',
            'category': 'Тестовая категория',
            'price': Decimal('100.50'),
            'quantity': Decimal('2'),
            'amount': Decimal('201.00'),
            'nds_type': 20,
            'nds_sum': Decimal('33.50'),
        }
        product = Product.objects.create(**product_data)
        self.assertEqual(product.product_name, 'Тестовый продукт')
        self.assertEqual(product.amount, Decimal('201.00'))

    def test_product_str_representation(self):
        product = Product.objects.create(
            user=self.user,
            product_name='Тестовый продукт',
        )
        self.assertEqual(str(product), 'Тестовый продукт')

    def test_product_with_zero_quantity(self):
        product_data = {
            'user': self.user,
            'product_name': 'Продукт с нулевым количеством',
            'quantity': Decimal('0'),
            'price': Decimal('10.00'),
            'amount': Decimal('0.00'),
        }
        product = Product.objects.create(**product_data)
        self.assertEqual(product.quantity, Decimal('0'))


class TestReceiptModel(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_seller.yaml',
        'receipt_product.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.seller = Seller.objects.get(pk=1)

    def test_receipt_creation(self):
        receipt_data = {
            'user': self.user,
            'account': self.account,
            'seller': self.seller,
            'receipt_date': timezone.now(),
            'number_receipt': 12345,
            'operation_type': 1,
            'total_sum': Decimal('500.00'),
            'nds10': Decimal('45.45'),
            'nds20': Decimal('0.00'),
            'manual': True,
        }
        receipt = Receipt.objects.create(**receipt_data)
        self.assertEqual(receipt.number_receipt, 12345)
        self.assertEqual(receipt.total_sum, Decimal('500.00'))

    def test_receipt_ordering(self):
        receipt2 = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=self.seller,
            receipt_date=timezone.now() + timedelta(hours=1),
            total_sum=Decimal('200.00'),
        )

        receipts = Receipt.objects.all()
        self.assertEqual(receipts[0], receipt2)

    def test_receipt_with_products(self):
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=self.seller,
            receipt_date=timezone.now(),
            total_sum=Decimal('100.00'),
        )

        product1 = Product.objects.create(
            user=self.user,
            product_name='Продукт 1',
            price=Decimal('50.00'),
            quantity=Decimal('1'),
            amount=Decimal('50.00'),
        )
        product2 = Product.objects.create(
            user=self.user,
            product_name='Продукт 2',
            price=Decimal('50.00'),
            quantity=Decimal('1'),
            amount=Decimal('50.00'),
        )

        receipt.product.add(product1, product2)
        self.assertEqual(receipt.product.count(), 2)


class TestForms(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_seller.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.seller = Seller.objects.get(pk=1)

    def test_seller_form_valid(self):
        form_data = {
            'name_seller': 'Тестовый продавец',
            'retail_place_address': 'ул. Тестовая, 1',
            'retail_place': 'Магазин "Тест"',
        }
        form = SellerForm(data=form_data)  # type: ignore[no-untyped-call]
        self.assertTrue(form.is_valid())

    def test_seller_form_empty_fields(self):
        form_data = {
            'name_seller': 'Тестовый продавец',
            'retail_place_address': '',
            'retail_place': '',
        }
        form = SellerForm(data=form_data)  # type: ignore[no-untyped-call]
        self.assertTrue(form.is_valid())

    def test_product_form_valid(self):
        form_data = {
            'product_name': 'Тестовый продукт',
            'price': '100.50',
            'quantity': '2',
            'amount': '201.00',
        }
        form = ProductForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_product_form_invalid_quantity(self):
        form_data = {
            'product_name': 'Тестовый продукт',
            'price': '100.50',
            'quantity': '0',
            'amount': '0.00',
        }
        form = ProductForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)

    def test_product_form_negative_quantity(self):
        form_data = {
            'product_name': 'Тестовый продукт',
            'price': '100.50',
            'quantity': '-1',
            'amount': '-100.50',
        }
        form = ProductForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)

    def test_receipt_form_valid(self):
        form_data = {
            'seller': self.seller.pk,
            'account': self.account.pk,
            'receipt_date': '2023-06-28 21:24',
            'number_receipt': '12345',
            'operation_type': '1',
            'total_sum': '500.00',
            'nds10': '45.45',
            'nds20': '0.00',
        }
        form = ReceiptForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_receipt_form_missing_required_fields(self):
        form_data = {
            'seller': self.seller.pk,
            'receipt_date': '2023-06-28 21:24',
            'number_receipt': '12345',
            'operation_type': '1',
            'total_sum': '500.00',
        }
        form = ReceiptForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('account', form.errors)

    def test_product_formset_valid(self):
        formset_data = {
            'form-TOTAL_FORMS': '2',
            'form-INITIAL_FORMS': '0',
            'form-MAX_NUM_FORMS': '10',
            'form-0-product_name': 'Продукт 1',
            'form-0-price': '100.00',
            'form-0-quantity': '1',
            'form-0-amount': '100.00',
            'form-1-product_name': 'Продукт 2',
            'form-1-price': '200.00',
            'form-1-quantity': '2',
            'form-1-amount': '400.00',
        }
        formset = ProductFormSet(data=formset_data)
        self.assertTrue(formset.is_valid())

    def test_upload_image_form_valid(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        test_file = SimpleUploadedFile(
            'test.jpg',
            b'fake-image-content',
            content_type='image/jpeg',
        )

        form_data = {
            'account': self.account.pk,
        }

        form = UploadImageForm(  # type: ignore[no-untyped-call]
            user=self.user,
            data=form_data,
            files={'file': test_file},
        )

        self.assertTrue(form.is_valid())


class TestReceiptFilter(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_seller.yaml',
        'receipt_product.yaml',
        'receipt_receipt.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.seller = Seller.objects.get(pk=1)

    def test_filter_by_seller(self):
        filter_data = {'name_seller': self.seller.pk}
        receipt_filter = ReceiptFilter(  # type: ignore[no-untyped-call]
            data=filter_data,
            queryset=Receipt.objects.all(),
            user=self.user,
        )
        filtered_qs = receipt_filter.qs
        self.assertTrue(all(receipt.seller == self.seller for receipt in filtered_qs))

    def test_filter_by_account(self):
        filter_data = {'account': self.account.pk}
        receipt_filter = ReceiptFilter(  # type: ignore[no-untyped-call]
            data=filter_data,
            queryset=Receipt.objects.all(),
            user=self.user,
        )
        filtered_qs = receipt_filter.qs
        self.assertTrue(all(receipt.account == self.account for receipt in filtered_qs))

    def test_filter_by_date_range(self):
        filter_data = {
            'receipt_date_after': '2023-01-01',
            'receipt_date_before': '2023-12-31',
        }
        receipt_filter = ReceiptFilter(  # type: ignore[no-untyped-call]
            data=filter_data,
            queryset=Receipt.objects.all(),
            user=self.user,
        )
        filtered_qs = receipt_filter.qs
        for receipt in filtered_qs:
            self.assertGreaterEqual(receipt.receipt_date.year, 2023)
            self.assertLessEqual(receipt.receipt_date.year, 2023)


class TestReceiptAPIs(APITestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_seller.yaml',
        'receipt_receipt.yaml',
        'receipt_product.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.seller = Seller.objects.get(pk=1)
        self.receipt = Receipt.objects.get(pk=1)
        self.client.force_authenticate(user=self.user)

    def test_receipt_list_api(self):
        url = reverse_lazy('receipts:api_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.json(), list)

    def test_receipt_list_api_unauthorized(self):
        self.client.force_authenticate(user=None)
        url = reverse_lazy('receipts:api_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_seller_detail_api(self):
        url = reverse_lazy('receipts:seller', kwargs={'id': self.seller.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['name_seller'], self.seller.name_seller)

    def test_seller_create_api(self):
        url = reverse_lazy('receipts:seller_create_api')
        data = {
            'name_seller': 'Новый продавец через API',
            'retail_place_address': 'ул. API, 1',
            'retail_place': 'Магазин API',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['name_seller'], 'Новый продавец через API')

    def test_data_url_api(self):
        url = reverse_lazy('receipts:receipt_image')
        data = {'data_url': 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD'}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.json())

    def test_data_url_api_invalid_data(self):
        url = reverse_lazy('receipts:receipt_image')
        data: dict[str, Any] = {}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_receipt_create_api(self):
        url = reverse_lazy('receipts:receipt_api_create')
        data: dict[str, Any] = {
            'user': self.user.pk,
            'finance_account': self.account.pk,
            'receipt_date': '2023-06-28T21:24:00Z',
            'total_sum': '500.00',
            'number_receipt': '12345',
            'operation_type': 1,
            'nds10': '45.45',
            'nds20': '0.00',
            'seller': {
                'name_seller': 'Продавец через API',
                'retail_place_address': 'ул. API, 1',
                'retail_place': 'Магазин API',
            },
            'product': [
                {
                    'product_name': 'Продукт 1',
                    'price': '100.00',
                    'quantity': '1',
                    'amount': '100.00',
                },
                {
                    'product_name': 'Продукт 2',
                    'price': '200.00',
                    'quantity': '2',
                    'amount': '400.00',
                },
            ],
        }
        response = self.client.post(
            url,
            json.dumps(data),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_receipt_create_api_duplicate(self):
        url = reverse_lazy('receipts:receipt_api_create')
        data = {
            'user': self.user.pk,
            'finance_account': self.account.pk,
            'receipt_date': self.receipt.receipt_date.isoformat(),
            'total_sum': str(self.receipt.total_sum),
            'number_receipt': str(self.receipt.number_receipt),
            'operation_type': self.receipt.operation_type,
            'seller': {
                'name_seller': 'Дублирующий продавец',
                'retail_place_address': 'ул. Дублирующая, 1',
                'retail_place': 'Магазин Дублирующий',
            },
            'product': [
                {
                    'product_name': 'Дублирующий продукт',
                    'price': '100.00',
                    'quantity': '1',
                    'amount': '100.00',
                },
            ],
        }
        response = self.client.post(
            url,
            json.dumps(data),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestServices(TestCase):
    def test_image_to_base64(self):
        test_file = SimpleUploadedFile(
            'test.jpg',
            b'fake-image-content',
            content_type='image/jpeg',
        )

        result = image_to_base64(test_file)
        self.assertTrue(result.startswith('data:image/jpeg;base64,'))
        self.assertIn('ZmFrZS1pbWFnZS1jb250ZW50', result)

    @patch('hasta_la_vista_money.receipts.services.OpenAI')
    def test_analyze_image_with_ai(self, mock_openai):
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = '{"test": "data"}'

        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        test_file = SimpleUploadedFile(
            'test.jpg',
            b'fake-image-content',
            content_type='image/jpeg',
        )

        result = analyze_image_with_ai(test_file)
        self.assertEqual(result, '{"test": "data"}')

        mock_client.chat.completions.create.assert_called_once()

    @patch('hasta_la_vista_money.receipts.services.OpenAI')
    def test_analyze_image_with_ai_error(self, mock_openai):
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = Exception('API Error')
        mock_openai.return_value = mock_client

        test_file = SimpleUploadedFile(
            'test.jpg',
            b'fake-image-content',
            content_type='image/jpeg',
        )

        with self.assertRaises(Exception):
            analyze_image_with_ai(test_file)


class TestUploadImageView(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)

    def test_upload_image_view_get(self):
        self.client.force_login(self.user)
        url = reverse_lazy('receipts:upload')
        response = self.client.get(url)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_upload_image_view_unauthorized(self):
        url = reverse_lazy('receipts:upload')
        response = self.client.get(url)
        self.assertRedirects(response, '/login/?next=/receipts/upload/')

    @patch('hasta_la_vista_money.receipts.views.analyze_image_with_ai')
    def test_upload_image_view_post(self, mock_analyze):
        mock_analyze.return_value = json.dumps(
            {
                'name_seller': 'Тестовый продавец',
                'total_sum': '100.00',
                'number_receipt': '12345',
                'receipt_date': '16.05.2023 19:35',
                'items': [
                    {
                        'product_name': 'Тестовый продукт',
                        'price': '50.00',
                        'quantity': '2',
                        'amount': '100.00',
                        'category': 'Продукты',
                    },
                ],
            },
        )

        self.client.force_login(self.user)
        url = reverse_lazy('receipts:upload')

        test_file = SimpleUploadedFile(
            'receipt.jpg',
            b'fake-receipt-image',
            content_type='image/jpeg',
        )

        data = {
            'account': self.account.pk,
            'file': test_file,
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        receipt = Receipt.objects.filter(user=self.user, number_receipt='12345').first()
        self.assertIsNotNone(receipt)


class TestProductByMonthView(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'receipt_seller.yaml',
        'receipt_receipt.yaml',
        'receipt_product.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)

    def test_product_by_month_view(self):
        self.client.force_login(self.user)
        url = reverse_lazy('receipts:products')
        response = self.client.get(url)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_product_by_month_view_unauthorized(self):
        url = reverse_lazy('receipts:products')
        response = self.client.get(url)
        self.assertRedirects(response, '/login/?next=/receipts/products')


class TestModelValidation(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)

    def test_receipt_negative_total_sum(self):
        seller = Seller.objects.create(
            user=self.user,
            name_seller='Тестовый продавец',
        )

        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=seller,
            receipt_date=timezone.now(),
            total_sum=Decimal('-100.00'),
        )

        self.assertEqual(receipt.total_sum, Decimal('-100.00'))

    def test_product_zero_price(self):
        product = Product.objects.create(
            user=self.user,
            product_name='Бесплатный продукт',
            price=Decimal('0.00'),
            quantity=Decimal('1'),
            amount=Decimal('0.00'),
        )

        self.assertEqual(product.price, Decimal('0.00'))
        self.assertEqual(product.amount, Decimal('0.00'))

    def test_seller_empty_name(self):
        seller = Seller.objects.create(
            user=self.user,
            name_seller='',
        )

        self.assertEqual(seller.name_seller, '')


class TestReceiptOperations(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.account = Account.objects.get(pk=1)
        self.seller = Seller.objects.create(
            user=self.user,
            name_seller='Тестовый продавец',
        )

    def test_receipt_operation_types(self):
        operation_types = [1, 2, 3, 4]

        for op_type in operation_types:
            receipt = Receipt.objects.create(
                user=self.user,
                account=self.account,
                seller=self.seller,
                receipt_date=timezone.now(),
                operation_type=op_type,
                total_sum=Decimal('100.00'),
            )
            self.assertEqual(receipt.operation_type, op_type)

    def test_receipt_manual_flag(self):
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=self.seller,
            receipt_date=timezone.now(),
            total_sum=Decimal('100.00'),
            manual=True,
        )

        self.assertTrue(receipt.manual)

    def test_receipt_nds_calculation(self):
        receipt = Receipt.objects.create(
            user=self.user,
            account=self.account,
            seller=self.seller,
            receipt_date=timezone.now(),
            total_sum=Decimal('120.00'),
            nds10=Decimal('10.91'),
            nds20=Decimal('0.00'),
        )

        self.assertEqual(receipt.nds10, Decimal('10.91'))
        self.assertEqual(receipt.nds20, Decimal('0.00'))


class TestReceiptPermissions(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
    ]

    def setUp(self) -> None:
        self.user1 = User.objects.get(pk=1)
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='test2@example.com',
            password='testpass123',  # nosec
        )
        self.account1 = Account.objects.get(pk=1)
        self.account2 = Account.objects.create(
            user=self.user2,
            name_account='Счет пользователя 2',
            balance=Decimal('1000.00'),
        )
        self.seller1 = Seller.objects.create(
            user=self.user1,
            name_seller='Продавец пользователя 1',
        )
        self.seller2 = Seller.objects.create(
            user=self.user2,
            name_seller='Продавец пользователя 2',
        )

    def test_user_can_only_see_own_receipts(self):
        receipt1 = Receipt.objects.create(
            user=self.user1,
            account=self.account1,
            seller=self.seller1,
            receipt_date=timezone.now(),
            total_sum=Decimal('100.00'),
        )
        self.client.force_login(self.user1)
        response = self.client.get(reverse_lazy('receipts:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

        receipts = response.context['receipts']
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0], receipt1)

    def test_user_can_only_see_own_sellers(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse_lazy('receipts:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

        seller_form = response.context['receipt_form'].fields['seller']
        seller_queryset = seller_form.queryset
        self.assertEqual(len(seller_queryset), 1)
        self.assertEqual(seller_queryset[0], self.seller1)

    def test_user_can_only_see_own_accounts(self):
        self.client.force_login(self.user1)
        response = self.client.get(reverse_lazy('receipts:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        account_form = response.context['receipt_form'].fields['account']
        account_queryset = account_form.queryset
        self.assertEqual(len(account_queryset), 2)
        for account in account_queryset:
            self.assertEqual(account.user, self.user1)
        self.assertNotIn(self.account2, account_queryset)
