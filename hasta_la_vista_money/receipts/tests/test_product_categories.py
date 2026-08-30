from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.signals import post_save
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategory,
    ProductCategorySource,
)
from hasta_la_vista_money.receipts.repositories import (
    ProductCategoryRepository,
    ProductRepository,
)
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    SellerCreateData,
)
from hasta_la_vista_money.receipts.services.signals import (
    seed_product_categories_for_new_user,
)

User = get_user_model()


class ProductCategoryTest(TestCase):
    def test_new_user_receives_starter_product_categories(self) -> None:
        user = User.objects.create_user(
            username='product-category-user',
            password='pass',  # nosec B106: test-only password
        )

        self.assertEqual(ProductCategory.objects.filter(user=user).count(), 21)
        self.assertTrue(
            ProductCategory.objects.filter(
                user=user,
                name='Прочее',
            ).exists(),
        )

    def test_category_name_is_normalized_and_unique_per_user(self) -> None:
        user = User.objects.create_user(
            username='category-normalization-user',
            password='pass',  # nosec B106: test-only password
        )
        ProductCategory.objects.filter(user=user).delete()
        category = ProductCategoryRepository().get_or_create_category(
            user=user,
            name='  Товары   ёлка ',
        )

        self.assertEqual(category.name, 'Товары ёлка')
        self.assertEqual(category.normalized_name, 'товары елка')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductCategory.objects.create(
                user=user,
                name='товары елка',
                normalized_name='товары елка',
            )

    def test_product_references_category_and_keeps_manual_source(self) -> None:
        user = User.objects.create_user(
            username='product-category-source-user',
            password='pass',  # nosec B106: test-only password
        )
        category = ProductCategory.objects.get(user=user, name='Прочее')

        product = Product.objects.create(
            user=user,
            product_name='Тестовый товар',
            category=category,
            category_source=ProductCategorySource.MANUAL,
            price=1,
            quantity=1,
            amount=1,
        )

        self.assertEqual(product.category, category)
        self.assertEqual(
            product.category_source,
            ProductCategorySource.MANUAL,
        )

    def test_renaming_category_updates_normalized_name(self) -> None:
        user = User.objects.create_user(
            username='category-rename-user',
            password='pass',  # nosec B106: test-only password
        )
        repository = ProductCategoryRepository()
        category = repository.get_or_create_category(
            user=user,
            name='Товары ёлка',
        )

        repository.rename_category(category, '  Другая   ёлка ')
        category.refresh_from_db()

        self.assertEqual(category.name, 'Другая ёлка')
        self.assertEqual(category.normalized_name, 'другая елка')

    def test_product_repository_rejects_foreign_user_category(self) -> None:
        first_user = User.objects.create_user(
            username='first-product-owner',
            password='pass',  # nosec B106: test-only password
        )
        second_user = User.objects.create_user(
            username='second-category-owner',
            password='pass',  # nosec B106: test-only password
        )
        category = ProductCategory.objects.get(
            user=second_user,
            name='Прочее',
        )

        with self.assertRaises(ValidationError):
            ProductRepository().create_product(
                user=first_user,
                product_name='Тестовый товар',
                category=category,
                price=1,
                quantity=1,
                amount=1,
            )


class ReceiptCreatorCategorySourceTest(TestCase):
    """Product rows keep the categorization stage that produced them."""

    def test_uses_category_source_reported_by_the_classifier(self) -> None:
        user = User.objects.create_user(
            username='creator-category-source-user',
            password='pass',  # nosec B106: test-only password
        )
        account = Account.objects.create(
            user=user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RU',
        )
        service = ApplicationContainer().receipts.receipt_creator_service()

        receipt = service.create_receipt_with_products(
            user=user,
            account=account,
            receipt_data=ReceiptCreateData(
                receipt_date=timezone.now(),
                total_sum=Decimal('10.00'),
                operation_type=1,
            ),
            seller_data=SellerCreateData(name_seller='Shop'),
            products_data=[
                {
                    'product_name': 'Кефир',
                    'category': 'Молочные продукты и яйца',
                    'category_source': 'name_match',
                    'price': '10.00',
                    'quantity': '1',
                    'amount': '10.00',
                },
            ],
            allow_insufficient_funds=True,
        )

        product = receipt.product.get()
        self.assertEqual(
            product.category_source,
            ProductCategorySource.NAME_MATCH,
        )

    def test_falls_back_to_writing_match_for_unknown_source(self) -> None:
        user = User.objects.create_user(
            username='creator-unknown-source-user',
            password='pass',  # nosec B106: test-only password
        )
        account = Account.objects.create(
            user=user,
            name_account='Wallet',
            balance=Decimal('1000.00'),
            currency='RU',
        )
        service = ApplicationContainer().receipts.receipt_creator_service()

        receipt = service.create_receipt_with_products(
            user=user,
            account=account,
            receipt_data=ReceiptCreateData(
                receipt_date=timezone.now(),
                total_sum=Decimal('10.00'),
                operation_type=1,
            ),
            seller_data=SellerCreateData(name_seller='Shop'),
            products_data=[
                {
                    'product_name': 'Кефир',
                    'category': 'Прочее',
                    'price': '10.00',
                    'quantity': '1',
                    'amount': '10.00',
                },
            ],
            allow_insufficient_funds=True,
        )

        product = receipt.product.get()
        self.assertEqual(
            product.category_source,
            ProductCategorySource.WRITING_MATCH,
        )


class ProductCategoryMigrationTest(TransactionTestCase):
    """Verify that the directory migration preserves historical rows."""

    migrate_from = [
        ('receipts', '0014_pendingreceipt_converted_receipt_and_more'),
    ]
    migrate_to = [('receipts', '0015_productcategory_and_more')]

    def setUp(self) -> None:
        self.executor = MigrationExecutor(transaction.get_connection())
        self.executor.migrate(self.migrate_from)
        old_apps = self.executor.loader.project_state(self.migrate_from).apps
        old_product_model = old_apps.get_model('receipts', 'Product')
        post_save.disconnect(seed_product_categories_for_new_user, sender=User)
        self.user = User.objects.create_user(
            username='migration-user',
            password='pass',  # nosec B106: test-only password
            theme='auto',
        )
        old_product_model.objects.create(
            user_id=self.user.pk,
            product_name='Курица',
            category='Мясо и Птица',
            price=1,
            quantity=1,
            amount=1,
        )
        old_product_model.objects.create(
            user_id=self.user.pk,
            product_name='Дипромета сусп. д/ин. 7мг/мл 1мл шприц №1',
            category='Прочее',
            price=1,
            quantity=1,
            amount=1,
        )
        old_product_model.objects.create(
            user_id=self.user.pk,
            product_name='Возврат оплаты',
            category='Прочее',
            price=1,
            quantity=1,
            amount=1,
        )

    def tearDown(self) -> None:
        self.executor = MigrationExecutor(transaction.get_connection())
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        post_save.connect(seed_product_categories_for_new_user, sender=User)

    def test_migration_moves_rows_to_approved_categories(self) -> None:
        self.executor = MigrationExecutor(transaction.get_connection())
        self.executor.migrate(self.migrate_to)
        apps = self.executor.loader.project_state(self.migrate_to).apps
        Product = apps.get_model('receipts', 'Product')

        products = Product.objects.select_related('category').order_by('id')

        self.assertEqual(products.count(), 3)
        self.assertEqual(products[0].category.name, 'Мясо и птица')
        self.assertEqual(products[1].category.name, 'Лекарства')
        self.assertIsNone(products[2].category)
        self.assertEqual(products[0].category_source, 'migrated')
