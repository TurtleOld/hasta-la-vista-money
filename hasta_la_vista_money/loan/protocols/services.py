"""Protocols for loan calculation service interfaces.

This module defines Protocol interfaces for loan calculation services,
enabling dependency injection and type checking.
"""

from datetime import date
from typing import Protocol, runtime_checkable

from hasta_la_vista_money.loan.models import Loan


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
        loan_amount: float,
        annual_interest_rate: float,
        period_loan: int,
    ) -> None: ...
