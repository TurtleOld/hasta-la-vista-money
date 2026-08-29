"""External fallback for receipt product categorization."""

import json
from enum import StrEnum
from typing import Any

from django.conf import settings

from core.repositories.protocols import ProductCategoryRepositoryProtocol
from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategory,
    ProductCategorySource,
)
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_category_name,
)
from hasta_la_vista_money.receipts.protocols.services import (
    ReceiptCategoryModelTransportProtocol,
)


class ExternalCategoryResponseError(ValueError):
    """Raised when an external category response is invalid."""


class ExternalCategoryAction(StrEnum):
    """Allowed structured-response actions."""

    EXISTING = 'existing'
    NEW = 'new'


class ExternalProductCategoryService:
    """Apply the optional external-model fallback to one product row."""

    def __init__(
        self,
        *,
        transport: ReceiptCategoryModelTransportProtocol | None,
        product_category_repository: ProductCategoryRepositoryProtocol,
    ) -> None:
        """Initialize the fallback service.

        Args:
            transport: Optional structured completion transport.
            product_category_repository: Owner category directory gateway.
        """
        self._transport = transport
        self._product_category_repository = product_category_repository

    @property
    def enabled(self) -> bool:
        """Return whether an external model transport is configured."""
        return self._transport is not None

    def categorize_product(self, product: Product) -> bool:
        """Choose an existing category for a product left uncategorized."""
        if self._transport is None:
            return False
        categories = list(
            self._product_category_repository.list_for_user(product.user),
        )
        action, category_name = self._request_decision(
            product=product,
            category_names=[category.name for category in categories],
        )
        category = self._resolve_category(
            product=product,
            action=action,
            category_name=category_name,
        )
        product.category = category
        product.category_source = ProductCategorySource.EXTERNAL_MODEL
        product.save(update_fields=['category', 'category_source'])
        return True

    def _request_decision(
        self,
        *,
        product: Product,
        category_names: list[str],
    ) -> tuple['ExternalCategoryAction', str]:
        """Request and validate one structured category decision."""
        if self._transport is None:
            raise RuntimeError('External category transport is disabled')
        try:
            response = self._transport.complete(
                messages=[
                    {
                        'role': 'system',
                        'content': (
                            'Выбери категорию товара из справочника владельца. '
                            'Не выбирай категорию «Прочее». Если подходящей '
                            'категории нет, предложи новую.'
                        ),
                    },
                    {
                        'role': 'user',
                        'content': json.dumps(
                            {
                                'product_name': product.product_name,
                                'categories': category_names,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_tokens=constants.RECEIPT_CATEGORY_MAX_RESPONSE_TOKENS,
                temperature=0,
                response_format=constants.RECEIPT_CATEGORY_RESPONSE_FORMAT,
            )
        except ValueError as error:
            raise ExternalCategoryResponseError(
                'External model returned a non-object response',
            ) from error
        return self._parse_response(response)

    def _resolve_category(
        self,
        *,
        product: Product,
        action: 'ExternalCategoryAction',
        category_name: str,
    ) -> ProductCategory:
        """Resolve a validated decision against the owner directory."""
        if normalize_product_category_name(category_name) == (
            normalize_product_category_name(
                constants.DEFAULT_PRODUCT_CATEGORY,
            )
        ):
            raise ExternalCategoryResponseError(
                'External model selected the default category',
            )
        if action is ExternalCategoryAction.NEW:
            category = self._product_category_repository.find_similar_by_name(
                user=product.user,
                name=category_name,
                minimum_similarity=(
                    settings.RECEIPT_CATEGORY_NEW_CATEGORY_SIMILARITY_THRESHOLD
                ),
            )
            if category is None:
                category = (
                    self._product_category_repository.get_or_create_category(
                        user=product.user,
                        name=category_name,
                    )
                )
        else:
            category = self._product_category_repository.get_by_name(
                user=product.user,
                name=category_name,
            )
        if category is None:
            raise ExternalCategoryResponseError(
                'External model selected a category outside the directory',
            )

        return category

    @staticmethod
    def _parse_response(
        response: dict[str, Any],
    ) -> tuple['ExternalCategoryAction', str]:
        try:
            content = response['choices'][0]['message']['content']
            decision = json.loads(content)
            if not isinstance(decision, dict) or set(decision) != {
                'action',
                'category',
            }:
                raise ExternalCategoryResponseError(
                    'External category response does not match its schema',
                )
            action = decision['action']
            category = decision['category']
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ExternalCategoryResponseError(
                'External model returned an invalid structured response',
            ) from error
        try:
            parsed_action = ExternalCategoryAction(action)
        except (TypeError, ValueError) as error:
            raise ExternalCategoryResponseError(
                'Unknown category action',
            ) from error
        if not isinstance(category, str) or not category.strip():
            raise ExternalCategoryResponseError('Category must be non-empty')
        if len(category) > constants.TWO_HUNDRED_FIFTY:
            raise ExternalCategoryResponseError('Category is too long')
        return parsed_action, category.strip()
