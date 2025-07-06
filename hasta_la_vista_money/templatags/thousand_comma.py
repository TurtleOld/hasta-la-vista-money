import decimal

from django import template

register = template.Library()

THOUSAND_MINUS_ONE = 999


@register.filter
def comma(number) -> str:
    """
    Функция разделения тысячных и миллионных.
    """
    try:
        if number is None or number == '':
            return '—'
        return f'{decimal.Decimal(str(number)):,.2f}'.replace(',', ' ')
    except (decimal.InvalidOperation, ValueError, TypeError):
        return '—'
