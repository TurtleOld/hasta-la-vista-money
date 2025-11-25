from datetime import date
from typing import Protocol, runtime_checkable

from hasta_la_vista_money.loan.models import Loan


@runtime_checkable
class LoanCalculationServiceProtocol(Protocol):
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
