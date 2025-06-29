"""Модуль задач для пакета loan."""

from datetime import date, datetime
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.shortcuts import get_object_or_404
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
    Функция по расчёту аннуитетных платежей.

    :param user_id:
    :param loan_id:
    :param start_date:
    :param loan_amount:
    :param annual_interest_rate:
    :param period_loan:
    :return:
    """
    if not isinstance(loan_amount, Decimal):
        loan_amount = Decimal(
            str(loan_amount),
        )  # Convert to string first to avoid precision issues
    if not isinstance(annual_interest_rate, Decimal):
        annual_interest_rate = Decimal(str(annual_interest_rate))
    if not isinstance(period_loan, Decimal):
        period_loan = Decimal(str(period_loan))

    NUMBER_TWELFTH_MONTH_YEAR = Decimal(12)
    HUNDRED = Decimal(100)

    monthly_interest_rate = (annual_interest_rate / NUMBER_TWELFTH_MONTH_YEAR) / HUNDRED

    monthly_payment = (
        loan_amount
        * (monthly_interest_rate * (1 + monthly_interest_rate) ** period_loan)
        / ((1 + monthly_interest_rate) ** period_loan - 1)
    )

    balance = loan_amount

    start_date = start_date + relativedelta(months=1)

    user = get_object_or_404(User, id=user_id)
    loan = get_object_or_404(Loan, id=loan_id)

    payment_schedules = []

    for _ in range(1, int(period_loan) + 1):
        interest = balance * monthly_interest_rate
        principal_payment = monthly_payment - interest
        balance -= principal_payment

        year = start_date.year
        month = start_date.month
        day = start_date.day
        current_date = date(year, month, day)

        next_date = start_date + relativedelta(months=1)

        payment_schedules.append(
            PaymentSchedule(
                user=user,
                loan=loan,
                date=current_date,
                balance=round(balance, 2),
                monthly_payment=round(monthly_payment, 2),
                interest=round(interest, 2),
                principal_payment=round(principal_payment, 2),
            ),
        )

        start_date = next_date

    PaymentSchedule.objects.bulk_create(payment_schedules)


def calculate_differentiated_loan(
    user_id,
    loan_id,
    start_date: datetime,
    loan_amount: Decimal,
    annual_interest_rate: Decimal,
    period_loan: int,
):
    """
    Функция по расчёту дифференцированных платежей.

    :param user_id:
    :param loan_id:
    :param start_date:
    :param loan_amount:
    :param annual_interest_rate:
    :param period_loan:
    :return:
    """
    # Ensure loan_amount is a Decimal
    if not isinstance(loan_amount, Decimal):
        loan_amount = Decimal(str(loan_amount))

    user = get_object_or_404(User, id=user_id)
    loan = Loan.objects.filter(id=loan_id).first()

    NUMBER_TWELFTH_MONTH_YEAR = Decimal(12)
    HUNDRED = Decimal(100)

    monthly_interest_rate = (annual_interest_rate / NUMBER_TWELFTH_MONTH_YEAR) / HUNDRED

    balance = loan_amount
    start_date = start_date + relativedelta(months=1)

    payment_schedules = []

    for _ in range(1, int(period_loan) + 1):
        interest = balance * monthly_interest_rate
        principal_payment = loan_amount / Decimal(period_loan)
        balance -= principal_payment
        monthly_payment = interest + principal_payment

        year = start_date.year
        month = start_date.month
        day = start_date.day
        current_date = date(year, month, day)

        next_date = start_date + relativedelta(months=1)

        payment_schedules.append(
            PaymentSchedule(
                user=user,
                loan=loan,
                date=current_date,
                balance=round(balance, 2),
                monthly_payment=round(monthly_payment, 2),
                interest=round(interest, 2),
                principal_payment=round(principal_payment, 2),
            ),
        )

        start_date = next_date

    PaymentSchedule.objects.bulk_create(payment_schedules)
