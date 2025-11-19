from dependency_injector import containers, providers

from hasta_la_vista_money.income.services.income_ops import IncomeOps


class IncomeContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()

    income_ops = providers.Factory(
        IncomeOps,
        account_service=core.account_service,
    )
