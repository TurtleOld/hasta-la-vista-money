import decimal
from typing import Any

from django import template

register = template.Library()

THOUSAND_MINUS_ONE = 999


@register.filter
def comma(number: Any) -> str:
    """
    Функция разделения тысячных и миллионных пробелами.
    Форматирует число с разделением тысяч пробелами.
    """
    try:
        if number is None or number == '':
            return '—'
        decimal_value = decimal.Decimal(str(number))
        formatted = f'{decimal_value:,.2f}'.replace(',', ' ')
        if '.00' in formatted:
            formatted = formatted.replace('.00', '')
        return formatted
    except (decimal.InvalidOperation, ValueError, TypeError):
        return '—'
