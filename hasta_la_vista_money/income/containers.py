from dependency_injector import containers, providers

from hasta_la_vista_money.income.protocols.services import IncomeServiceProtocol
from hasta_la_vista_money.income.repositories import (
    IncomeCategoryRepository,
    IncomeRepository,
)
from hasta_la_vista_money.income.services.income_ops import IncomeService


class IncomeContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()

    income_repository = providers.Singleton(IncomeRepository)
    income_category_repository = providers.Singleton(IncomeCategoryRepository)

    income_ops: providers.Singleton[IncomeServiceProtocol] = (
        providers.Singleton(
            IncomeService,
            account_service=core.account_service,
            income_repository=income_repository,
        )
    )
