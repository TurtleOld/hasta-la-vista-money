"""Normalization used by the product category directory and product names."""

import re

_SPACE_RE = re.compile(r'\s+')
_WORD_RE = re.compile(r'[^0-9a-zа-яё]+')


def normalize_product_category_name(value: str) -> str:
    """Return the canonical form used to compare category names."""
    return _SPACE_RE.sub(' ', value.casefold().replace('ё', 'е')).strip()


def normalize_product_name(value: str) -> str:
    """Return the canonical form used to compare product names."""
    normalized = value.lower().replace('ё', 'е')
    normalized = _WORD_RE.sub(' ', normalized)
    return _SPACE_RE.sub(' ', normalized).strip()
