import decimal
from typing import Any

from django import template

register = template.Library()

THOUSAND_MINUS_ONE = 999


@register.filter
def comma(number: Any) -> str:
    """Format number with space as thousand separator.

    Formats number with space as thousand separator for thousands
    and millions.

    Args:
        number: Number to format (can be int, float, Decimal, or string).

    Returns:
        Formatted string with space as thousand separator, or '—' if
        number is None, empty, or invalid.
    """
    try:
        if number is None or number == '':
            return '—'
        decimal_value = decimal.Decimal(str(number))
        return f'{decimal_value:,.2f}'.replace(',', ' ')
    except (decimal.InvalidOperation, ValueError, TypeError):
        return '—'
