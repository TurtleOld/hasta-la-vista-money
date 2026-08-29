"""Detect twin product categories using the optional external model."""

import json
from typing import Any

from core.repositories.protocols import ProductCategoryRepositoryProtocol
from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.models import ProductCategory
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_category_name,
)
from hasta_la_vista_money.receipts.protocols.services import (
    ReceiptCategoryModelTransportProtocol,
)
from hasta_la_vista_money.users.models import User


class CategoryTwinDetectionError(ValueError):
    """Raised when an external twin-detection response is invalid."""


class CategoryTwinDetectionService:
    """Find pairs of categories that mean the same kind of purchase."""

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

    def find_duplicate_pairs(
        self,
        user: User,
    ) -> list[tuple[ProductCategory, ProductCategory]]:
        """Return resolved duplicate pairs from the user's directory."""
        if self._transport is None:
            return []
        categories = list(
            self._product_category_repository.list_for_user(user),
        )
        if len(categories) < constants.TWO:
            return []
        raw_pairs = self._request_pairs(
            [category.name for category in categories],
        )
        return self._resolve_pairs(categories, raw_pairs)

    def _request_pairs(
        self,
        category_names: list[str],
    ) -> list[tuple[str, str]]:
        if self._transport is None:
            raise RuntimeError('External category transport is disabled')
        try:
            response = self._transport.complete(
                messages=[
                    {
                        'role': 'system',
                        'content': (
                            'Найди пары категорий, которые обозначают один '
                            'и тот же вид покупки. Возвращай только пары '
                            'категорий из списка; не включай пару, если '
                            'категории действительно различны.'
                        ),
                    },
                    {
                        'role': 'user',
                        'content': json.dumps(
                            {'categories': category_names},
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_tokens=constants.RECEIPT_CATEGORY_MAX_RESPONSE_TOKENS,
                temperature=0,
                response_format=constants.RECEIPT_CATEGORY_TWIN_RESPONSE_FORMAT,
            )
        except ValueError as error:
            raise CategoryTwinDetectionError(
                'External model returned a non-object response',
            ) from error
        return self._parse_response(response)

    @staticmethod
    def _parse_response(
        response: dict[str, Any],
    ) -> list[tuple[str, str]]:
        try:
            content = response['choices'][0]['message']['content']
            decision = json.loads(content)
            pairs = decision['pairs']
            if not isinstance(pairs, list):
                raise CategoryTwinDetectionError(
                    'Twin-detection response does not match its schema',
                )
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise CategoryTwinDetectionError(
                'External model returned an invalid structured response',
            ) from error

        result: list[tuple[str, str]] = []
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            first = pair.get('first')
            second = pair.get('second')
            if (
                isinstance(first, str)
                and isinstance(second, str)
                and first.strip()
                and second.strip()
            ):
                result.append((first.strip(), second.strip()))
        return result

    @staticmethod
    def _resolve_pairs(
        categories: list[ProductCategory],
        raw_pairs: list[tuple[str, str]],
    ) -> list[tuple[ProductCategory, ProductCategory]]:
        by_name = {
            normalize_product_category_name(category.name): category
            for category in categories
        }
        result: list[tuple[ProductCategory, ProductCategory]] = []
        for first, second in raw_pairs:
            category_a = by_name.get(
                normalize_product_category_name(first),
            )
            category_b = by_name.get(
                normalize_product_category_name(second),
            )
            if (
                category_a is None
                or category_b is None
                or category_a.pk == category_b.pk
            ):
                continue
            result.append((category_a, category_b))
        return result


__all__ = [
    'CategoryTwinDetectionError',
    'CategoryTwinDetectionService',
]
