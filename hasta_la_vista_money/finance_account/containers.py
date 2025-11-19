from dependency_injector import containers, providers

from hasta_la_vista_money.finance_account.services import TransferService


class FinanceAccountContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()

    account_service = core.account_service
    transfer_service = providers.Factory(TransferService)

