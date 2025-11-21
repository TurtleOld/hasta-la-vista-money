from dependency_injector import containers, providers

from hasta_la_vista_money.loan.protocols.services import (
    LoanCalculationServiceProtocol,
)
from hasta_la_vista_money.loan.repositories import (
    LoanRepository,
    PaymentMakeLoanRepository,
    PaymentScheduleRepository,
)
from hasta_la_vista_money.loan.services.loan_calculation import (
    LoanCalculationService,
)


class LoanContainer(containers.DeclarativeContainer):
    loan_repository = providers.Singleton(LoanRepository)
    payment_make_loan_repository = providers.Singleton(
        PaymentMakeLoanRepository,
    )
    payment_schedule_repository = providers.Singleton(
        PaymentScheduleRepository,
    )

    loan_calculation_service: providers.Factory[
        LoanCalculationServiceProtocol
    ] = providers.Factory(LoanCalculationService)
