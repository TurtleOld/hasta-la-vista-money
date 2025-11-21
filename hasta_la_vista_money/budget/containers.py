from dependency_injector import containers, providers

from hasta_la_vista_money.budget.repositories import (
    DateListRepository,
    PlanningRepository,
)


class BudgetContainer(containers.DeclarativeContainer):
    expense = providers.DependenciesContainer()
    income = providers.DependenciesContainer()

    planning_repository = providers.Singleton(PlanningRepository)
    date_list_repository = providers.Singleton(DateListRepository)

