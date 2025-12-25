"""Loan tasks module.

This module provides tasks for loan calculations including annuity
and differentiated loan payment schedules.
"""

from datetime import date
from decimal import Decimal

from hasta_la_vista_money.loan.services.loan_calculation import (
    calculate_annuity_loan_db,
    calculate_differentiated_loan_db,
)


def calculate_annuity_loan(
    user_id: int,
    loan_id: int,
    start_date: date,
    loan_amount: Decimal,
    annual_interest_rate: Decimal,
    period_loan: int,
) -> None:
    """Calculate annuity loan payment schedule.

    Wrapper function for calculating annuity loan payment schedule
    and saving it to database. Each payment is equal in amount.

    Args:
        user_id: User ID who owns the loan.
        loan_id: Loan ID to calculate schedule for.
        start_date: Loan start date.
        loan_amount: Total loan amount.
        annual_interest_rate: Annual interest rate as decimal.
        period_loan: Loan period in months.
    """
    calculate_annuity_loan_db(
        user_id=user_id,
        loan_id=loan_id,
        start_date=start_date,
        loan_amount=loan_amount,
        annual_interest_rate=annual_interest_rate,
        period_loan=period_loan,
    )


def calculate_differentiated_loan(
    user_id: int,
    loan_id: int,
    start_date: date,
    loan_amount: Decimal,
    annual_interest_rate: Decimal,
    period_loan: int,
) -> None:
    """Calculate differentiated loan payment schedule.

    Wrapper function for calculating differentiated loan payment schedule
    and saving it to database. Principal payment is constant, interest
    decreases over time.

    Args:
        user_id: User ID who owns the loan.
        loan_id: Loan ID to calculate schedule for.
        start_date: Loan start date.
        loan_amount: Total loan amount.
        annual_interest_rate: Annual interest rate as decimal.
        period_loan: Loan period in months.
    """
    calculate_differentiated_loan_db(
        user_id=user_id,
        loan_id=loan_id,
        start_date=start_date,
        loan_amount=loan_amount,
        annual_interest_rate=annual_interest_rate,
        period_loan=period_loan,
    )
