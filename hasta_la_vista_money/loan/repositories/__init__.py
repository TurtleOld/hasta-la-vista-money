"""Репозитории для loan модуля."""

from hasta_la_vista_money.loan.repositories.loan_repository import (
    LoanRepository,
)
from hasta_la_vista_money.loan.repositories.payment_make_loan_repository import (  # noqa: E501
    PaymentMakeLoanRepository,
)
from hasta_la_vista_money.loan.repositories.payment_schedule_repository import (
    PaymentScheduleRepository,
)

__all__ = [
    'LoanRepository',
    'PaymentMakeLoanRepository',
    'PaymentScheduleRepository',
]
