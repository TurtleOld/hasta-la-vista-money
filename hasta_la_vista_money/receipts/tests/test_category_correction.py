"""Tests for remembering human product-category corrections."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from hasta_la_vista_money.constants import RECEIPT_OPERATION_PURCHASE
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategorySource,
    ProductNameCategoryMapping,
    Receipt,
    Seller,
)
from hasta_la_vista_money.receipts.repositories import (
    ProductCategoryRepository,
    ProductNameCategoryMappingRepository,
)
from hasta_la_vista_money.receipts.services.category_classifier import (
    ReceiptItemCategoryService,
    normalize_product_name,
)
from hasta_la_vista_money.receipts.services.product_category_correction import (
    ProductCategoryCorrectionService,
)

User = get_user_model()


class ProductCategoryCorrectionServiceTests(TestCase):
    """The correction service pins a name and reclassifies history."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='correction-user',
            password='pass',  # nosec B106: test-only password
            email='correction@example.com',
        )
        self.category_repo = ProductCategoryRepository()
        self.service = ProductCategoryCorrectionService(
            ProductNameCategoryMappingRepository(),
        )

    def test_correction_pins_name_mapping(self) -> None:
        category = self.category_repo.get_or_create_category(
            user=self.user,
            name='Молочные продукты и яйца',
        )

        self.service.apply_correction(
            user=self.user,
            product_name='Кефир Здравушка 900г',
            category=category,
        )

        mapping = ProductNameCategoryMapping.objects.get(user=self.user)
        self.assertEqual(
            mapping.normalized_product_name,
            normalize_product_name('Кефир Здравушка 900г'),
        )
        self.assertEqual(mapping.category, category)

    def test_correction_updates_existing_mapping(self) -> None:
        first = self.category_repo.get_or_create_category(
            user=self.user,
            name='Напитки',
        )
        second = self.category_repo.get_or_create_category(
            user=self.user,
            name='Молочные продукты и яйца',
        )
        ProductNameCategoryMapping.objects.create(
            user=self.user,
            normalized_product_name='кефир здравушка',
            category=first,
        )

        self.service.apply_correction(
            user=self.user,
            product_name='Кефир Здравушка',
            category=second,
        )

        mapping = ProductNameCategoryMapping.objects.get(user=self.user)
        self.assertEqual(mapping.category, second)

    def test_reclassifies_same_name_rows_retroactively(self) -> None:
        old_category = self.category_repo.get_or_create_category(
            user=self.user,
            name='Напитки',
        )
        new_category = self.category_repo.get_or_create_category(
            user=self.user,
            name='Молочные продукты и яйца',
        )
        other_row = Product.objects.create(
            user=self.user,
            product_name='кефир здравушка',
            category=old_category,
            category_source=ProductCategorySource.WRITING_MATCH,
            price=1,
            quantity=1,
            amount=1,
        )

        self.service.apply_correction(
            user=self.user,
            product_name='Кефир Здравушка',
            category=new_category,
        )

        other_row.refresh_from_db()
        self.assertEqual(other_row.category, new_category)
        self.assertEqual(
            other_row.category_source,
            ProductCategorySource.NAME_MATCH,
        )

    def test_manual_rows_are_never_reclassified(self) -> None:
        old_category = self.category_repo.get_or_create_category(
            user=self.user,
            name='Напитки',
        )
        new_category = self.category_repo.get_or_create_category(
            user=self.user,
            name='Молочные продукты и яйца',
        )
        manual_row = Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка',
            category=old_category,
            category_source=ProductCategorySource.MANUAL,
            price=1,
            quantity=1,
            amount=1,
        )

        self.service.apply_correction(
            user=self.user,
            product_name='Кефир Здравушка',
            category=new_category,
        )

        manual_row.refresh_from_db()
        self.assertEqual(manual_row.category, old_category)
        self.assertEqual(
            manual_row.category_source,
            ProductCategorySource.MANUAL,
        )

    def test_excludes_supplied_product_ids(self) -> None:
        category = self.category_repo.get_or_create_category(
            user=self.user,
            name='Напитки',
        )
        protected = Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка',
            category=category,
            category_source=ProductCategorySource.WRITING_MATCH,
            price=1,
            quantity=1,
            amount=1,
        )

        self.service.apply_correction(
            user=self.user,
            product_name='Кефир Здравушка',
            category=category,
            exclude_product_ids=[protected.pk],
        )

        protected.refresh_from_db()
        self.assertEqual(protected.category, category)
        self.assertEqual(
            protected.category_source,
            ProductCategorySource.WRITING_MATCH,
        )

    def test_none_category_is_a_noop(self) -> None:
        self.service.apply_correction(
            user=self.user,
            product_name='Кефир Здравушка',
            category=None,
        )

        self.assertFalse(
            ProductNameCategoryMapping.objects.filter(user=self.user).exists(),
        )

    def test_pinned_mapping_wins_over_writing_match(self) -> None:
        drinks = self.category_repo.get_or_create_category(
            user=self.user,
            name='Напитки',
        )
        dairy = self.category_repo.get_or_create_category(
            user=self.user,
            name='Молочные продукты и яйца',
        )
        Product.objects.create(
            user=self.user,
            product_name='Кефир',
            category=drinks,
            category_source=ProductCategorySource.WRITING_MATCH,
            price=1,
            quantity=1,
            amount=1,
        )

        self.service.apply_correction(
            user=self.user,
            product_name='Кефир Здравушка',
            category=dairy,
        )

        category = ReceiptItemCategoryService().categorize(
            user=self.user,
            product_name='Кефир Здравушка',
        )

        self.assertEqual(category, dairy.name)
        mapping = ProductNameCategoryMapping.objects.get(user=self.user)
        self.assertEqual(mapping.category, dairy)


class ReceiptUpdateCategoryCorrectionTests(TestCase):
    """Editing a receipt corrects the category and pins the name."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='update-correction-user',
            password='pass',  # nosec B106: test-only password
            email='update-correction@example.com',
            is_active=True,
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Основной счёт',
            balance=Decimal('10000.00'),
            type_account='Debit',
            currency='RUB',
        )
        self.seller = Seller.objects.create(
            user=self.user,
            name_seller='Тестовый магазин',
        )
        self.category_repo = ProductCategoryRepository()
        self.drinks = self.category_repo.get_or_create_category(
            user=self.user,
            name='Напитки',
        )
        self.dairy = self.category_repo.get_or_create_category(
            user=self.user,
            name='Молочные продукты и яйца',
        )

        self.product = Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка',
            category=self.drinks,
            category_source=ProductCategorySource.WRITING_MATCH,
            price=Decimal('100.00'),
            quantity=Decimal('2.00'),
            amount=Decimal('200.00'),
        )
        self.other_row = Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка',
            category=self.drinks,
            category_source=ProductCategorySource.WRITING_MATCH,
            price=Decimal('50.00'),
            quantity=Decimal('1.00'),
            amount=Decimal('50.00'),
        )
        self.receipt = Receipt.objects.create(
            user=self.user,
            seller=self.seller,
            account=self.account,
            receipt_date='2024-01-15 12:00:00',
            number_receipt=12345,
            operation_type=RECEIPT_OPERATION_PURCHASE,
            total_sum=Decimal('200.00'),
            manual=True,
        )
        self.receipt.product.add(self.product)
        self.account.balance -= self.receipt.total_sum
        self.account.save()

        self.client = Client()
        self.client.force_login(self.user)

    def test_correction_pins_mapping_and_reclassifies_history(self) -> None:
        update_data = {
            'seller': self.seller.pk,
            'account': self.account.pk,
            'receipt_date': '2024-01-15 12:00:00',
            'number_receipt': 12345,
            'operation_type': 1,
            'total_sum': '200.00',
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-product_name': 'Кефир Здравушка',
            'form-0-category': self.dairy.pk,
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

        corrected = self.receipt.product.get()
        self.assertEqual(corrected.category, self.dairy)
        self.assertEqual(
            corrected.category_source,
            ProductCategorySource.MANUAL,
        )

        mapping = ProductNameCategoryMapping.objects.get(user=self.user)
        self.assertEqual(mapping.normalized_product_name, 'кефир здравушка')
        self.assertEqual(mapping.category, self.dairy)

        self.other_row.refresh_from_db()
        self.assertEqual(self.other_row.category, self.dairy)
        self.assertEqual(
            self.other_row.category_source,
            ProductCategorySource.NAME_MATCH,
        )

    def test_unchanged_category_is_not_pinned(self) -> None:
        update_data = {
            'seller': self.seller.pk,
            'account': self.account.pk,
            'receipt_date': '2024-01-15 12:00:00',
            'number_receipt': 12345,
            'operation_type': 1,
            'total_sum': '200.00',
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-product_name': 'Кефир Здравушка',
            'form-0-category': self.drinks.pk,
            'form-0-price': '100.00',
            'form-0-quantity': '2.00',
            'form-0-amount': '200.00',
        }

        self.client.post(
            reverse('receipts:update', kwargs={'pk': self.receipt.pk}),
            data=update_data,
            follow=True,
        )

        self.assertFalse(
            ProductNameCategoryMapping.objects.filter(user=self.user).exists(),
        )
