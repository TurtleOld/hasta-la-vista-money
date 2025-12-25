from datetime import datetime
from decimal import Decimal
from typing import TypedDict


class GracePeriodInfoDict(TypedDict, total=False):
    """Information about credit card grace period.

    Attributes:
        purchase_month: Purchase month in MM.YYYY format.
        purchase_start: Start date of purchase period.
        purchase_end: End date of purchase period.
        grace_end: End date of grace period.
        debt_for_month: Debt amount for the purchase month.
        payments_for_period: Payments made during the grace period.
        final_debt: Final debt amount after grace period.
        is_overdue: Whether the debt is overdue.
        days_until_due: Number of days until payment is due.
    """

    purchase_month: str
    purchase_start: datetime
    purchase_end: datetime
    grace_end: datetime
    debt_for_month: Decimal
    payments_for_period: Decimal
    final_debt: Decimal
    is_overdue: bool
    days_until_due: int


class PaymentScheduleItemDict(TypedDict):
    """Payment schedule item.

    Attributes:
        date: Payment date.
        amount: Payment amount.
    """

    date: datetime
    amount: Decimal


class PaymentScheduleStatementDict(TypedDict):
    """Payment schedule statement item.

    Attributes:
        statement_date: Statement date.
        payment_due_date: Payment due date.
        remaining_debt: Remaining debt amount.
        min_payment: Minimum payment amount.
        statement_number: Statement number.
    """

    statement_date: datetime
    payment_due_date: datetime
    remaining_debt: Decimal
    min_payment: Decimal
    statement_number: int


class RaiffeisenbankScheduleDict(TypedDict, total=False):
    """Payment schedule for Raiffeisenbank credit card.

    Attributes:
        first_purchase_date: Date of first purchase in the period.
        grace_end_date: End date of grace period.
        total_initial_debt: Total initial debt amount.
        final_debt: Final debt amount after payments.
        payments_schedule: List of payment schedule statements.
        days_until_grace_end: Number of days until grace period ends.
        is_overdue: Whether the debt is overdue.
    """

    first_purchase_date: datetime
    grace_end_date: datetime
    total_initial_debt: Decimal
    final_debt: Decimal
    payments_schedule: list[PaymentScheduleItemDict]
    days_until_grace_end: int
    is_overdue: bool
