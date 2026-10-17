"""Protocols for loan calculation service interfaces.

This module defines Protocol interfaces for loan calculation services,
enabling dependency injection and type checking.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from hasta_la_vista_money.loan.models import Loan, PaymentMakeLoan
from hasta_la_vista_money.users.models import User


@runtime_checkable
class LoanCalculationServiceProtocol(Protocol):
    """Protocol for loan calculation service interface.

    Defines the contract for calculating loan payment schedules
    including annuity and differentiated payment methods.
    """

    def run(
        self,
        *,
        type_loan: str,
        user_id: int,
        loan: Loan,
        start_date: date,
        loan_amount: Decimal,
        annual_interest_rate: Decimal,
        period_loan: int,
    ) -> None: ...


@runtime_checkable
class LoanPaymentServiceProtocol(Protocol):
    """Protocol for posting a loan payment as a financial movement."""

    def post_payment(
        self,
        *,
        user: User,
        loan_id: int,
        account_id: int | None,
        amount: Decimal,
        date: datetime,
    ) -> PaymentMakeLoan: ...
