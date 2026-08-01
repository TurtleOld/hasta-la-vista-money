from dependency_injector import containers, providers

from hasta_la_vista_money.deposits.protocols import DepositServiceProtocol
from hasta_la_vista_money.deposits.repositories import DepositRepository
from hasta_la_vista_money.deposits.services import DepositService


class DepositContainer(containers.DeclarativeContainer):
    finance_account = providers.DependenciesContainer()

    deposit_repository = providers.Singleton(DepositRepository)
    deposit_service: providers.Factory[DepositServiceProtocol] = (
        providers.Factory(
            DepositService,
            deposit_repository=deposit_repository,
            account_repository=finance_account.account_repository,
        )
    )
