"""External fallback for receipt product categorization."""

import json
from typing import Any, Final

from django.conf import settings

from core.repositories.protocols import ProductCategoryRepositoryProtocol
from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import (
    Product,
    ProductCategorySource,
)
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_category_name,
)
from hasta_la_vista_money.receipts.protocols.services import (
    ReceiptCategoryModelTransportProtocol,
)

_MAX_RESPONSE_TOKENS: Final = 100
_RESPONSE_FORMAT: Final[dict[str, Any]] = {
    'type': 'json_schema',
    'json_schema': {
        'name': 'receipt_product_category',
        'strict': True,
        'schema': {
            'type': 'object',
            'properties': {
                'action': {
                    'type': 'string',
                    'enum': ['existing', 'new'],
                },
                'category': {'type': 'string'},
            },
            'required': ['action', 'category'],
            'additionalProperties': False,
        },
    },
}


class ExternalCategoryResponseError(ValueError):
    """Raised when an external category response is invalid."""


class ExternalProductCategoryService:
    """Apply the optional external-model fallback to one product row."""

    def __init__(
        self,
        *,
        transport: ReceiptCategoryModelTransportProtocol | None,
        product_category_repository: ProductCategoryRepositoryProtocol,
    ) -> None:
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
        category_names = [category.name for category in categories]
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
            max_tokens=_MAX_RESPONSE_TOKENS,
            temperature=0,
            response_format=_RESPONSE_FORMAT,
        )
        action, category_name = self._parse_response(response)
        if normalize_product_category_name(category_name) == (
            normalize_product_category_name(
                constants.DEFAULT_PRODUCT_CATEGORY,
            )
        ):
            raise ExternalCategoryResponseError(
                'External model selected the default category',
            )
        if action == 'new':
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

        product.category = category
        product.category_source = ProductCategorySource.EXTERNAL_MODEL
        product.save(update_fields=['category', 'category_source'])
        return True

    @staticmethod
    def _parse_response(response: dict[str, Any]) -> tuple[str, str]:
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
        if action not in {'existing', 'new'}:
            raise ExternalCategoryResponseError('Unknown category action')
        if not isinstance(category, str) or not category.strip():
            raise ExternalCategoryResponseError('Category must be non-empty')
        if len(category) > constants.TWO_HUNDRED_FIFTY:
            raise ExternalCategoryResponseError('Category is too long')
        return action, category.strip()
