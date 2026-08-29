"""Normalization used by the product category directory."""

import re

_SPACE_RE = re.compile(r'\s+')


def normalize_product_category_name(value: str) -> str:
    """Return the canonical form used to compare category names."""
    return _SPACE_RE.sub(' ', value.casefold().replace('ё', 'е')).strip()
