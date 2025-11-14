"""Модуль задач для пакета loan."""

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
    calculate_differentiated_loan_db(
        user_id=user_id,
        loan_id=loan_id,
        start_date=start_date,
        loan_amount=loan_amount,
        annual_interest_rate=annual_interest_rate,
        period_loan=period_loan,
    )
