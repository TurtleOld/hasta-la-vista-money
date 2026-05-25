"""Lightweight receipt item categorization by user history and rules."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any, Final

from hasta_la_vista_money.receipts.models import Product

if TYPE_CHECKING:
    from collections.abc import Iterable

    from hasta_la_vista_money.users.models import User

DEFAULT_PRODUCT_CATEGORY: Final[str] = 'Прочее'
_HISTORY_LIMIT: Final[int] = 2000
_WORD_RE: Final[re.Pattern[str]] = re.compile(r'[^0-9a-zа-яё]+')
_SPACE_RE: Final[re.Pattern[str]] = re.compile(r'\s+')

_CATEGORY_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        'Молочные продукты',
        (
            'кефир',
            'молоко',
            'йогурт',
            'творог',
            'сметана',
            'сыр',
            'сливки',
            'ряженка',
            'масло сливочное',
        ),
    ),
    ('Овощи', ('томат', 'помидор', 'огур', 'перец', 'картоф', 'морков')),
    ('Фрукты', ('яблок', 'банан', 'груш', 'апельсин', 'лимон', 'мандарин')),
    ('Хлеб', ('хлеб', 'батон', 'булк', 'лаваш', 'багет')),
    ('Мясо', ('куриц', 'говяд', 'свинин', 'фарш', 'колбас', 'сосиск')),
    ('Рыба', ('рыб', 'лосос', 'семг', 'сельд', 'тунец', 'кревет')),
    ('Напитки', ('вода', 'сок', 'чай', 'кофе', 'напиток', 'лимонад')),
    ('Бакалея', ('рис', 'греч', 'макарон', 'мука', 'сахар', 'соль', 'круп')),
    ('Сладости', ('шоколад', 'конфет', 'печень', 'вафл', 'морожен')),
    ('Бытовая химия', ('порошок', 'средство', 'гель', 'мыло', 'шампун')),
    ('Гигиена', ('зубн', 'паста', 'щетк', 'салфет', 'туалет')),
)


def normalize_product_name(value: str) -> str:
    """Normalize product name for history matching and rule checks."""
    normalized = value.lower().replace('ё', 'е')
    normalized = _WORD_RE.sub(' ', normalized)
    return _SPACE_RE.sub(' ', normalized).strip()


class ReceiptItemCategoryService:
    """Categorize receipt items using user's history before static rules."""

    def categorize(self, *, user: User, product_name: str) -> str:
        """Return category for a product name."""
        normalized_name = normalize_product_name(product_name)
        if not normalized_name:
            return DEFAULT_PRODUCT_CATEGORY

        history_category = self._history_categories(user).get(normalized_name)
        if history_category:
            return history_category

        return self._rule_category(normalized_name) or DEFAULT_PRODUCT_CATEGORY

    def categorize_items(
        self,
        *,
        user: User,
        items: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return item copies with missing/default categories filled in."""
        categorized_items: list[dict[str, Any]] = []
        for item in items:
            categorized_item = dict(item)
            existing_category = str(categorized_item.get('category') or '')
            if (
                not existing_category
                or existing_category == DEFAULT_PRODUCT_CATEGORY
            ):
                product_name = str(categorized_item.get('product_name') or '')
                categorized_item['category'] = self.categorize(
                    user=user,
                    product_name=product_name,
                )
            categorized_items.append(categorized_item)
        return categorized_items

    def _history_categories(self, user: User) -> dict[str, str]:
        rows = (
            Product.objects.filter(user=user)
            .exclude(category='')
            .order_by('-created_at')
            .values_list('product_name', 'category')[:_HISTORY_LIMIT]
        )
        categories_by_name: defaultdict[str, Counter[str]] = defaultdict(
            Counter,
        )
        for product_name, category in rows:
            normalized_name = normalize_product_name(str(product_name))
            normalized_category = str(category).strip()
            if normalized_name and normalized_category:
                categories_by_name[normalized_name][normalized_category] += 1

        return {
            normalized_name: category_counts.most_common(1)[0][0]
            for normalized_name, category_counts in categories_by_name.items()
        }

    def _rule_category(self, normalized_name: str) -> str | None:
        for category, markers in _CATEGORY_RULES:
            if any(marker in normalized_name for marker in markers):
                return category
        return None


__all__ = [
    'DEFAULT_PRODUCT_CATEGORY',
    'ReceiptItemCategoryService',
    'normalize_product_name',
]
