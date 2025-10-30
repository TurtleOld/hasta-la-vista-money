from __future__ import annotations

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.shortcuts import get_object_or_404

from hasta_la_vista_money.loan.models import Loan, PaymentSchedule
from hasta_la_vista_money.users.models import User


def calculate_annuity_schedule(
    amount: float,
    annual_rate: float,
    months: int,
) -> dict:
    monthly_rate = annual_rate / 100 / 12
    payment_raw = (
        amount
        * (monthly_rate * (1 + monthly_rate) ** months)
        / ((1 + monthly_rate) ** months - 1)
        if monthly_rate
        else amount / months
    )
    schedule = []
    payments = []
    remaining = amount
    for i in range(1, months):
        payment = round(payment_raw, 2)
        interest = remaining * monthly_rate
        principal = payment - round(interest, 2)
        schedule.append(
            {
                'month': i,
                'payment': payment,
                'interest': round(interest, 2),
                'principal': round(principal, 2),
                'balance': max(0, round(remaining - principal, 2)),
            },
        )
        payments.append(payment)
        remaining -= principal
    interest = remaining * monthly_rate
    last_payment = round(remaining + interest, 2)
    schedule.append(
        {
            'month': months,
            'payment': last_payment,
            'interest': round(interest, 2),
            'principal': round(remaining, 2),
            'balance': 0,
        },
    )
    payments.append(last_payment)
    total_payment = sum(payments)
    overpayment = total_payment - amount
    return {
        'schedule': schedule,
        'total_payment': total_payment,
        'overpayment': round(overpayment, 2),
        'monthly_payment': round(payment_raw, 2),
    }


def calculate_differentiated_schedule(
    amount: float,
    annual_rate: float,
    months: int,
) -> dict:
    monthly_rate = annual_rate / 100 / 12
    principal_payment = amount / months
    schedule = []
    total_payment = 0
    remaining = amount
    for i in range(1, months + 1):
        interest = remaining * monthly_rate
        payment = principal_payment + interest
        payment_rounded = round(payment, 2)
        total_payment += payment_rounded
        schedule.append(
            {
                'month': i,
                'payment': payment_rounded,
                'interest': round(interest, 2),
                'principal': round(principal_payment, 2),
                'balance': max(0, round(remaining - principal_payment, 2)),
            },
        )
        remaining -= principal_payment
    overpayment = total_payment - amount
    return {
        'schedule': schedule,
        'total_payment': total_payment,
        'overpayment': round(overpayment, 2),
    }


def _persist_schedule(
    *,
    user_id: int,
    loan_id: int,
    start_date: date,
    schedule_data: dict,
) -> None:
    user = get_object_or_404(User, id=user_id)
    loan = get_object_or_404(Loan, id=loan_id)

    payment_schedules: list[PaymentSchedule] = []
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


def calculate_annuity_loan_db(
    *,
    user_id: int,
    loan_id: int,
    start_date: date,
    loan_amount,
    annual_interest_rate,
    period_loan,
) -> None:
    if not isinstance(loan_amount, Decimal):
        loan_amount = Decimal(str(loan_amount))
    if not isinstance(annual_interest_rate, Decimal):
        annual_interest_rate = Decimal(str(annual_interest_rate))
    if not isinstance(period_loan, Decimal):
        period_loan = Decimal(str(period_loan))

    schedule_data = calculate_annuity_schedule(
        float(loan_amount),
        float(annual_interest_rate),
        int(period_loan),
    )
    _persist_schedule(
        user_id=user_id,
        loan_id=loan_id,
        start_date=start_date,
        schedule_data=schedule_data,
    )


def calculate_differentiated_loan_db(
    *,
    user_id: int,
    loan_id: int,
    start_date: date,
    loan_amount,
    annual_interest_rate,
    period_loan,
) -> None:
    if not isinstance(loan_amount, Decimal):
        loan_amount = Decimal(str(loan_amount))
    if not isinstance(annual_interest_rate, Decimal):
        annual_interest_rate = Decimal(str(annual_interest_rate))
    if not isinstance(period_loan, Decimal):
        period_loan = Decimal(str(period_loan))

    schedule_data = calculate_differentiated_schedule(
        float(loan_amount),
        float(annual_interest_rate),
        int(period_loan),
    )
    _persist_schedule(
        user_id=user_id,
        loan_id=loan_id,
        start_date=start_date,
        schedule_data=schedule_data,
    )


class LoanCalculationService:
    @staticmethod
    def run(
        *,
        type_loan: str,
        user_id: int,
        loan: Loan,
        start_date: date,
        loan_amount: float,
        annual_interest_rate: float,
        period_loan: int,
    ) -> None:
        if type_loan == 'Annuity':
            calculate_annuity_loan_db(
                user_id=user_id,
                loan_id=loan.pk,
                start_date=start_date,
                loan_amount=loan_amount,
                annual_interest_rate=annual_interest_rate,
                period_loan=period_loan,
            )
        elif type_loan == 'Differentiated':
            calculate_differentiated_loan_db(
                user_id=user_id,
                loan_id=loan.pk,
                start_date=start_date,
                loan_amount=loan_amount,
                annual_interest_rate=annual_interest_rate,
                period_loan=period_loan,
            )
        else:
            return
