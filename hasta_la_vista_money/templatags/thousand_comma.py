import decimal

from django import template

register = template.Library()

THOUSAND_MINUS_ONE = 999


@register.filter
def comma(number: float) -> str | None:
    """
    Функция разделения тысячных и миллионных.

    :param number:
    :type number: float
    :return: str | None
    """

    if number:
        return f'{decimal.Decimal(number):,.2f}'.replace(',', ' ')
    return decimal.Decimal(0)
