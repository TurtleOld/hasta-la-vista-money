import json
from decimal import Decimal
from typing import Any
from unittest.mock import Mock, patch

from celery.exceptions import Retry
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategory,
    ProductCategorySource,
    Receipt,
    Seller,
)
from hasta_la_vista_money.receipts.repositories import (
    ProductCategoryRepository,
)
from hasta_la_vista_money.receipts.services.external_category import (
    ExternalCategoryResponseError,
    ExternalProductCategoryService,
)
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    SellerCreateData,
)
from hasta_la_vista_money.receipts.tasks import categorize_receipt_products

User = get_user_model()


class RecordingTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.request: dict[str, Any] | None = None

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.request = kwargs
        return self.response


class ExternalProductCategoryServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='external-category-user',
            password='pass',  # nosec B106: test-only password
        )
        self.other = ProductCategory.objects.get(
            user=self.user,
            name='Прочее',
        )
        ProductCategoryRepository().get_or_create_category(
            user=self.user,
            name='Сладости и снеки',
        )
        self.product = Product.objects.create(
            user=self.user,
            product_name='Батончик мюсли с клюквой',
            category=self.other,
            price=1,
            quantity=1,
            amount=1,
        )

    def test_selects_existing_category_with_structured_request(self) -> None:
        transport = RecordingTransport(
            {
                'choices': [
                    {
                        'message': {
                            'content': json.dumps(
                                {
                                    'action': 'existing',
                                    'category': 'Сладости и снеки',
                                },
                            ),
                        },
                    },
                ],
            },
        )
        service = ExternalProductCategoryService(
            transport=transport,
            product_category_repository=ProductCategoryRepository(),
        )

        changed = service.categorize_product(self.product)

        self.product.refresh_from_db()
        self.assertTrue(changed)
        if self.product.category is None:
            self.fail('Product category was not assigned')
        self.assertEqual(self.product.category.name, 'Сладости и снеки')
        self.assertEqual(
            self.product.category_source,
            ProductCategorySource.EXTERNAL_MODEL,
        )
        if transport.request is None:
            self.fail('External model was not called')
        self.assertEqual(
            transport.request['response_format']['type'],
            'json_schema',
        )
        messages = transport.request['messages']
        self.assertIn(self.product.product_name, messages[-1]['content'])
        self.assertIn('Сладости и снеки', messages[-1]['content'])

    def test_rejects_response_that_only_claims_schema_compliance(self) -> None:
        transport = RecordingTransport(
            {
                'choices': [
                    {
                        'message': {
                            'content': json.dumps(
                                {
                                    'action': 'existing',
                                    'category': 'Сладости и снеки',
                                    'unsupported': True,
                                },
                            ),
                        },
                    },
                ],
            },
        )
        service = ExternalProductCategoryService(
            transport=transport,
            product_category_repository=ProductCategoryRepository(),
        )

        with self.assertRaises(ExternalCategoryResponseError):
            service.categorize_product(self.product)

        self.product.refresh_from_db()
        self.assertEqual(self.product.category, self.other)

    def test_rejects_default_category_as_external_decision(self) -> None:
        transport = RecordingTransport(
            {
                'choices': [
                    {
                        'message': {
                            'content': json.dumps(
                                {
                                    'action': 'existing',
                                    'category': 'Прочее',
                                },
                            ),
                        },
                    },
                ],
            },
        )
        service = ExternalProductCategoryService(
            transport=transport,
            product_category_repository=ProductCategoryRepository(),
        )

        with self.assertRaises(ExternalCategoryResponseError):
            service.categorize_product(self.product)

        self.product.refresh_from_db()
        self.assertEqual(self.product.category, self.other)

    @override_settings(
        RECEIPT_CATEGORY_NEW_CATEGORY_SIMILARITY_THRESHOLD=0.3,
    )
    def test_reuses_similar_category_instead_of_creating_proposal(self) -> None:
        repository = ProductCategoryRepository()
        existing = repository.get_or_create_category(
            user=self.user,
            name='Домашняя выпечка',
        )
        transport = RecordingTransport(
            {
                'choices': [
                    {
                        'message': {
                            'content': json.dumps(
                                {
                                    'action': 'new',
                                    'category': 'Домашняя выпечка свежая',
                                },
                            ),
                        },
                    },
                ],
            },
        )
        service = ExternalProductCategoryService(
            transport=transport,
            product_category_repository=repository,
        )

        changed = service.categorize_product(self.product)

        self.product.refresh_from_db()
        self.assertTrue(changed)
        self.assertEqual(self.product.category, existing)
        self.assertFalse(
            ProductCategory.objects.filter(
                user=self.user,
                name='Домашняя выпечка свежая',
            ).exists(),
        )

    @override_settings(
        RECEIPT_CATEGORY_NEW_CATEGORY_SIMILARITY_THRESHOLD=0.99,
    )
    def test_creates_sufficiently_distinct_category(self) -> None:
        transport = RecordingTransport(
            {
                'choices': [
                    {
                        'message': {
                            'content': json.dumps(
                                {
                                    'action': 'new',
                                    'category': 'Товары для аквариума',
                                },
                            ),
                        },
                    },
                ],
            },
        )
        service = ExternalProductCategoryService(
            transport=transport,
            product_category_repository=ProductCategoryRepository(),
        )

        changed = service.categorize_product(self.product)

        self.product.refresh_from_db()
        self.assertTrue(changed)
        if self.product.category is None:
            self.fail('Product category was not assigned')
        self.assertEqual(self.product.category.name, 'Товары для аквариума')
        self.assertEqual(
            self.product.category_source,
            ProductCategorySource.EXTERNAL_MODEL,
        )


class CategorizeReceiptProductsTaskTests(TestCase):
    def test_receipt_creation_enqueues_fallback_after_commit(self) -> None:
        user = User.objects.create_user(
            username='enqueue-external-category-user',
            password='pass',  # nosec B106: test-only password
        )
        account = Account.objects.create(
            user=user,
            name_account='Wallet',
            balance=Decimal('100.00'),
            currency='RU',
        )
        service = ApplicationContainer().receipts.receipt_creator_service()

        with (
            patch(
                'hasta_la_vista_money.receipts.services.receipt_creator.'
                'current_app.send_task',
            ) as send_task,
            self.captureOnCommitCallbacks(execute=True),
        ):
            receipt = service.create_receipt_with_products(
                user=user,
                account=account,
                receipt_data=ReceiptCreateData(
                    receipt_date=timezone.now(),
                    total_sum=Decimal('1.00'),
                    operation_type=1,
                ),
                seller_data=SellerCreateData(name_seller='Shop'),
                products_data=[
                    {
                        'product_name': 'Неизвестный товар',
                        'category': 'Прочее',
                        'price': '1.00',
                        'quantity': '1',
                        'amount': '1.00',
                    },
                ],
                allow_insufficient_funds=True,
            )

        send_task.assert_called_once_with(
            'receipts.categorize_receipt_products',
            args=[receipt.pk],
        )

    def test_disabled_model_does_not_make_external_call(self) -> None:
        user = User.objects.create_user(
            username='disabled-external-category-user',
            password='pass',  # nosec B106: test-only password
        )
        category = ProductCategory.objects.get(user=user, name='Прочее')
        product = Product.objects.create(
            user=user,
            product_name='Неизвестный товар',
            category=category,
            price=1,
            quantity=1,
            amount=1,
        )
        account = Account.objects.create(
            user=user,
            name_account='Wallet',
            balance=Decimal('100.00'),
            currency='RU',
        )
        seller = Seller.objects.create(user=user, name_seller='Shop')
        receipt = Receipt.objects.create(
            receipt_date=timezone.now(),
            total_sum=Decimal('1.00'),
            operation_type=1,
            user=user,
            account=account,
            seller=seller,
        )
        receipt.product.add(product)
        service = Mock(enabled=False)

        with (
            patch(
                'hasta_la_vista_money.receipts.tasks.'
                '_get_external_product_category_service',
                return_value=service,
            ),
            patch('hasta_la_vista_money.receipts.tasks.logger.info') as log,
        ):
            categorize_receipt_products(receipt.pk)

        service.categorize_product.assert_not_called()
        product.refresh_from_db()
        self.assertEqual(product.category, category)
        log.assert_called_once_with(
            'receipt_external_category_skipped',
            receipt_id=receipt.pk,
            reason='disabled',
            product_count=1,
        )

    def test_invalid_response_is_logged_and_retried(self) -> None:
        user = User.objects.create_user(
            username='retry-external-category-user',
            password='pass',  # nosec B106: test-only password
        )
        category = ProductCategory.objects.get(user=user, name='Прочее')
        product = Product.objects.create(
            user=user,
            product_name='Неизвестный товар',
            category=category,
            price=1,
            quantity=1,
            amount=1,
        )
        account = Account.objects.create(
            user=user,
            name_account='Wallet',
            balance=Decimal('100.00'),
            currency='RU',
        )
        seller = Seller.objects.create(user=user, name_seller='Shop')
        receipt = Receipt.objects.create(
            receipt_date=timezone.now(),
            total_sum=Decimal('1.00'),
            operation_type=1,
            user=user,
            account=account,
            seller=seller,
        )
        receipt.product.add(product)
        service = Mock(enabled=True)
        service.categorize_product.side_effect = ExternalCategoryResponseError(
            'invalid response',
        )

        with (
            patch(
                'hasta_la_vista_money.receipts.tasks.'
                '_get_external_product_category_service',
                return_value=service,
            ),
            patch('hasta_la_vista_money.receipts.tasks.logger.warning') as log,
            patch.object(
                categorize_receipt_products,
                'retry',
                side_effect=Retry(),
            ) as retry,
            self.assertRaises(Retry),
        ):
            categorize_receipt_products(receipt.pk)

        self.assertEqual(categorize_receipt_products.max_retries, 2)
        retry.assert_called_once()
        log.assert_called_once_with(
            'receipt_external_category_failed',
            receipt_id=receipt.pk,
            product_id=product.pk,
            reason='invalid_response',
            error='invalid response',
        )
