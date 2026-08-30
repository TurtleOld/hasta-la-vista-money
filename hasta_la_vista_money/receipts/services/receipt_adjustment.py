"""Calculations for differences between a receipt total and its items."""

from decimal import Decimal, InvalidOperation
from typing import Any

_ADJUSTMENT_QUANTUM = Decimal('0.01')


def calculate_receipt_adjustment(
    total_sum: Decimal,
    items: list[dict[str, Any]],
) -> Decimal:
    """Return the rounded difference between receipt total and item totals."""
    item_total = Decimal(0)
    for item in items:
        try:
            item_total += Decimal(str(item.get('amount', 0)))
        except (InvalidOperation, TypeError, ValueError):
            continue
    return (total_sum - item_total).quantize(_ADJUSTMENT_QUANTUM)


def requires_adjustment_confirmation(
    total_sum: Decimal,
    adjustment: Decimal,
) -> bool:
    """Return whether an adjustment requires explicit confirmation."""
    return abs(adjustment) > max(
        _ADJUSTMENT_QUANTUM,
        total_sum.copy_abs() * Decimal('0.01'),
    )
