"""Currency utilities.

This module provides functions for working with currencies,
including getting currency choices and default currency.
"""

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Final, cast

from django.utils.translation import get_language


@lru_cache
def _get_currencies_rates() -> dict[str, dict[str, str]]:
    """Get currency rates from JSON file.

    Returns:
        Dictionary mapping currency codes to currency data.
    """
    path = Path(__file__).parent / 'currencies.json'
    data = cast(
        'list[dict[str, str]]',
        json.loads(path.read_text(encoding='utf-8')),
    )
    return {x['code_name']: x for x in data}


def get_default_currency() -> str:
    """Get default currency code.

    Returns:
        Default currency code (RUB).
    """
    return 'RUB'


def currency_choices(lang: str | None = None) -> list[tuple[str, str]]:
    """Get currency choices for forms.

    Args:
        lang: Language code. If None, uses current Django language.

    Returns:
        List of (code, name) tuples for form choices, with default
        currency (RUB) first.
    """
    lang = (lang or get_language() or 'ru').lower()
    use_english = lang.startswith('en')
    data = _get_currencies_rates()

    sort_field = 'english_name' if use_english else 'russian_name'

    choices = [
        (
            code_name,
            row[sort_field]
            if row.get(sort_field)
            else row.get('russian_name', code_name),
        )
        for code_name, row in sorted(
            data.items(),
            key=lambda item: (
                item[1].get(sort_field)
                or item[1].get('russian_name')
                or item[0]
            ).casefold(),
        )
    ]

    default_currency = get_default_currency()
    default_choice = next(
        (choice for choice in choices if choice[0] == default_currency),
        None,
    )

    if default_choice:
        choices.remove(default_choice)
        choices.insert(0, default_choice)

    return choices


_CURRENCY_PRECISION: Final[dict[str, Decimal]] = {
    'BHD': Decimal('0.001'),
    'IQD': Decimal('0.001'),
    'JOD': Decimal('0.001'),
    'KWD': Decimal('0.001'),
    'LYD': Decimal('0.001'),
    'OMR': Decimal('0.001'),
    'TND': Decimal('0.001'),
    'JPY': Decimal(1),
    'KRW': Decimal(1),
    'VND': Decimal(1),
    'IDR': Decimal(1),
    'BYR': Decimal(1),
    'CLP': Decimal(1),
    'CVE': Decimal(1),
    'DJF': Decimal(1),
    'GNF': Decimal(1),
    'ISK': Decimal(1),
    'KMF': Decimal(1),
    'PYG': Decimal(1),
    'RWF': Decimal(1),
    'UGX': Decimal(1),
    'VUV': Decimal(1),
    'XAF': Decimal(1),
    'XOF': Decimal(1),
    'XPF': Decimal(1),
}


def get_currency_precision(currency_code: str) -> Decimal:
    """Return the smallest currency unit for a given ISO 4217 code.

    Most currencies use 0.01 (two decimal places). Known exceptions:
    - Japanese yen (JPY), Korean won (KRW), and others use 1 (integer).
    - Bahraini dinar (BHD), Kuwaiti dinar (KWD), and others use 0.001.

    Args:
        currency_code: A 3-character ISO 4217 currency code (e.g. 'RUB').

    Returns:
        The minimal unit as a Decimal (e.g. Decimal('0.01'), Decimal('1')).
    """
    return _CURRENCY_PRECISION.get(currency_code.upper(), Decimal('0.01'))
