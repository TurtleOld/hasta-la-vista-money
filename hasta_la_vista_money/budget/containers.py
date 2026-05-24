from dependency_injector import containers, providers

from hasta_la_vista_money.budget.repositories import (
    BudgetRepository,
    DateListRepository,
    PlanningRepository,
)
from hasta_la_vista_money.budget.services.budget import BudgetService


class BudgetContainer(containers.DeclarativeContainer):
    transactions = providers.DependenciesContainer()

    planning_repository = providers.Singleton(PlanningRepository)
    date_list_repository = providers.Singleton(DateListRepository)
    budget_repository = providers.Singleton(BudgetRepository)

    budget_service = providers.Factory(
        BudgetService,
        transaction_repository=transactions.transaction_repository,
        planning_repository=planning_repository,
        budget_repository=budget_repository,
    )
