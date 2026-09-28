"""Invariants of a single receipt product line.

Shared by every intake path (FNS, API, forms) so they cannot disagree on
which lines are acceptable. Free lines (a gift, a bag, a 100% discount)
are valid: price and amount may be zero, quantity must be positive.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Final

_KOPECK: Final = Decimal('0.01')


class ProductLineError(StrEnum):
    """Why a product line was rejected."""

    NEGATIVE_PRICE = 'negative_price'
    NON_POSITIVE_QUANTITY = 'non_positive_quantity'
    NEGATIVE_AMOUNT = 'negative_amount'
    AMOUNT_MISMATCH = 'amount_mismatch'


def is_weighed(quantity: Decimal) -> bool:
    """Return whether the line is sold by weight (fractional quantity)."""
    return quantity != quantity.to_integral_value()


def check_product_line(
    *,
    price: Decimal,
    quantity: Decimal,
    amount: Decimal,
) -> ProductLineError | None:
    """Return the first violated invariant of a line, or ``None``."""
    if price < 0:
        return ProductLineError.NEGATIVE_PRICE
    if quantity <= 0:
        return ProductLineError.NON_POSITIVE_QUANTITY
    if amount < 0:
        return ProductLineError.NEGATIVE_AMOUNT
    if is_weighed(quantity):
        # Weighed goods: the receipt's per-kg price is rounded to kopecks
        # for display, so multiplying it back by the printed weight does
        # not reliably reproduce the line's real sum. The reported amount
        # is authoritative for these lines.
        return None
    expected_amount = (price * quantity).quantize(_KOPECK)
    if abs(amount - expected_amount) > _KOPECK:
        return ProductLineError.AMOUNT_MISMATCH
    return None
