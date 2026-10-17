from dependency_injector import containers, providers

from hasta_la_vista_money.finance_account.repositories.account_repository import (  # noqa: E501
    AccountRepository,
)
from hasta_la_vista_money.loan.protocols.services import (
    LoanCalculationServiceProtocol,
    LoanPaymentServiceProtocol,
)
from hasta_la_vista_money.loan.repositories import (
    LoanRepository,
    PaymentMakeLoanRepository,
    PaymentScheduleRepository,
)
from hasta_la_vista_money.loan.services.loan_calculation import (
    LoanCalculationService,
)
from hasta_la_vista_money.loan.services.loan_payment import LoanPaymentService


class LoanContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()

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

    loan_payment_service: providers.Factory[LoanPaymentServiceProtocol] = (
        providers.Factory(
            LoanPaymentService,
            account_service=core.account_service,
            account_repository=providers.Singleton(AccountRepository),
            loan_repository=loan_repository,
            payment_repository=payment_make_loan_repository,
        )
    )
