"""Модуль задач для пакета loan."""

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.shortcuts import get_object_or_404

from hasta_la_vista_money.loan.loan_calculator import (
    calculate_annuity_schedule,
    calculate_differentiated_schedule,
)
from hasta_la_vista_money.loan.models import Loan, PaymentSchedule
from hasta_la_vista_money.users.models import User


def calculate_annuity_loan(
    user_id,
    loan_id,
    start_date,
    loan_amount,
    annual_interest_rate,
    period_loan,
):
    """
    Функция по расчёту аннуитетных платежей (по-банковски, с округлением каждого платежа).
    """
    if not isinstance(loan_amount, Decimal):
        loan_amount = Decimal(str(loan_amount))
    if not isinstance(annual_interest_rate, Decimal):
        annual_interest_rate = Decimal(str(annual_interest_rate))
    if not isinstance(period_loan, Decimal):
        period_loan = Decimal(str(period_loan))

    user = get_object_or_404(User, id=user_id)
    loan = get_object_or_404(Loan, id=loan_id)

    # Используем банковский расчёт
    schedule_data = calculate_annuity_schedule(
        float(loan_amount),
        float(annual_interest_rate),
        int(period_loan),
    )
    payment_schedules = []
    current_date = start_date + relativedelta(months=1)
    for payment in schedule_data['schedule']:
        payment_schedules.append(
            PaymentSchedule(
                user=user,
                loan=loan,
                date=date(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                ),
                balance=payment['balance'],
                monthly_payment=payment['payment'],
                interest=payment['interest'],
                principal_payment=payment['principal'],
            ),
        )
        current_date = current_date + relativedelta(months=1)
    PaymentSchedule.objects.bulk_create(payment_schedules)


def calculate_differentiated_loan(
    user_id,
    loan_id,
    start_date,
    loan_amount,
    annual_interest_rate,
    period_loan,
):
    """
    Функция по расчёту дифференцированных платежей (по-банковски, с округлением каждого платежа).
    """
    if not isinstance(loan_amount, Decimal):
        loan_amount = Decimal(str(loan_amount))
    if not isinstance(annual_interest_rate, Decimal):
        annual_interest_rate = Decimal(str(annual_interest_rate))
    if not isinstance(period_loan, Decimal):
        period_loan = Decimal(str(period_loan))

    user = get_object_or_404(User, id=user_id)
    loan = get_object_or_404(Loan, id=loan_id)

    # Используем банковский расчёт
    schedule_data = calculate_differentiated_schedule(
        float(loan_amount),
        float(annual_interest_rate),
        int(period_loan),
    )
    payment_schedules = []
    current_date = start_date + relativedelta(months=1)
    for payment in schedule_data['schedule']:
        payment_schedules.append(
            PaymentSchedule(
                user=user,
                loan=loan,
                date=date(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                ),
                balance=payment['balance'],
                monthly_payment=payment['payment'],
                interest=payment['interest'],
                principal_payment=payment['principal'],
            ),
        )
        current_date = current_date + relativedelta(months=1)
    PaymentSchedule.objects.bulk_create(payment_schedules)
