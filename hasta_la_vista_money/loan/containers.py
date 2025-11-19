from dependency_injector import containers, providers

from hasta_la_vista_money.loan.services.loan_calculation import (
    LoanCalculationService,
)


class LoanContainer(containers.DeclarativeContainer):
    loan_calculation_service = providers.Factory(LoanCalculationService)
