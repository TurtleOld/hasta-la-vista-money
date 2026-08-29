"""Tests for the optional external receipt-category fallback."""

import json
from decimal import Decimal
from typing import Any
from unittest.mock import Mock, call, patch

from celery.exceptions import Retry
from django.test import TestCase, override_settings
from django.utils import timezone

from config.containers import ApplicationContainer
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategory,
    ProductCategorySource,
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
from hasta_la_vista_money.receipts.tasks import categorize_receipt_product
from hasta_la_vista_money.users.models import User


class RecordingTransport:
    """Record structured requests and return a configured response."""

    def __init__(
        self,
        response: dict[str, Any] | ValueError,
    ) -> None:
        """Store the response or transport validation error."""
        self.response = response
        self.request: dict[str, Any] | None = None

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        """Record a completion request and return its configured result."""
        self.request = kwargs
        if isinstance(self.response, ValueError):
            raise self.response
        return self.response


class ExternalProductCategoryServiceTests(TestCase):
    """Verify decisions, validation, and category resolution."""

    user: User
    other: ProductCategory
    product: Product

    @classmethod
    def setUpTestData(cls) -> None:
        """Create a reusable owner directory and unresolved product."""
        cls.user = User.objects.create_user(
            username='external-category-user',
            password='pass',  # nosec B106: test-only password
        )
        cls.other = ProductCategory.objects.get(
            user=cls.user,
            name='Прочее',
        )
        ProductCategoryRepository().get_or_create_category(
            user=cls.user,
            name='Сладости и снеки',
        )
        cls.product = Product.objects.create(
            user=cls.user,
            product_name='Батончик мюсли с клюквой',
            category=cls.other,
            price=1,
            quantity=1,
            amount=1,
        )

    def test_selects_existing_category_with_structured_request(self) -> None:
        """Use an owner category and request strict JSON schema output."""
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
        """Reject unexpected fields even when the provider returns JSON."""
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
        """Keep the product unresolved when the model chooses Other."""
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
        """Reuse a sufficiently similar owner category for new proposals."""
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
        """Create a genuinely distinct category in the owner directory."""
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

    def test_normalizes_transport_value_error_for_task_retry(self) -> None:
        """Convert a malformed top-level response into a domain error."""
        service = ExternalProductCategoryService(
            transport=RecordingTransport(ValueError('non-object response')),
            product_category_repository=ProductCategoryRepository(),
        )

        with self.assertRaises(ExternalCategoryResponseError):
            service.categorize_product(self.product)


class CategorizeReceiptProductTaskTests(TestCase):
    """Verify post-commit dispatch and isolated product task behavior."""

    user: User
    category: ProductCategory
    product: Product

    @classmethod
    def setUpTestData(cls) -> None:
        """Create one unresolved product shared by task tests."""
        cls.user = User.objects.create_user(
            username='external-category-task-user',
            password='pass',  # nosec B106: test-only password
        )
        cls.category = ProductCategory.objects.get(
            user=cls.user,
            name=constants.DEFAULT_PRODUCT_CATEGORY,
        )
        cls.product = Product.objects.create(
            user=cls.user,
            product_name='Неизвестный товар',
            category=cls.category,
            category_source=ProductCategorySource.WRITING_MATCH,
            price=1,
            quantity=1,
            amount=1,
        )

    def test_receipt_creation_enqueues_fallback_after_commit(self) -> None:
        """Dispatch a separate post-commit task for each fallback product."""
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
                    total_sum=Decimal('2.00'),
                    operation_type=1,
                ),
                seller_data=SellerCreateData(name_seller='Shop'),
                products_data=[
                    {
                        'product_name': 'Неизвестный товар 1',
                        'category': 'Прочее',
                        'price': '1.00',
                        'quantity': '1',
                        'amount': '1.00',
                    },
                    {
                        'product_name': 'Неизвестный товар 2',
                        'category': 'Прочее',
                        'price': '1.00',
                        'quantity': '1',
                        'amount': '1.00',
                    },
                ],
                allow_insufficient_funds=True,
            )

        product_ids = list(
            receipt.product.order_by('pk').values_list('pk', flat=True),
        )
        self.assertEqual(send_task.call_count, 2)
        send_task.assert_has_calls(
            [
                call(
                    constants.RECEIPT_EXTERNAL_CATEGORY_TASK_NAME,
                    args=[product_id],
                )
                for product_id in product_ids
            ],
        )

    def test_disabled_model_does_not_make_external_call(self) -> None:
        """Skip without contacting a transport when configuration is absent."""
        service = Mock(enabled=False)

        with (
            patch(
                'hasta_la_vista_money.receipts.tasks.'
                '_get_external_product_category_service',
                return_value=service,
            ),
            patch('hasta_la_vista_money.receipts.tasks.logger.info') as log,
        ):
            categorize_receipt_product(self.product.pk)

        service.categorize_product.assert_not_called()
        self.product.refresh_from_db()
        self.assertEqual(self.product.category, self.category)
        log.assert_called_once_with(
            'receipt_external_category_skipped',
            product_id=self.product.pk,
            reason='disabled',
        )

    def test_invalid_response_is_logged_and_retried(self) -> None:
        """Log invalid structured responses and request Celery retry."""
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
                categorize_receipt_product,
                'retry',
                side_effect=Retry(),
            ) as retry,
            self.assertRaises(Retry),
        ):
            categorize_receipt_product(self.product.pk)

        self.assertEqual(categorize_receipt_product.max_retries, 2)
        retry.assert_called_once()
        log.assert_called_once_with(
            'receipt_external_category_failed',
            product_id=self.product.pk,
            reason='invalid_response',
            error='invalid response',
        )
