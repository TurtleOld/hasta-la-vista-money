from dependency_injector import containers, providers

from hasta_la_vista_money.budget.repositories import (
    DateListRepository,
    PlanningRepository,
)
from hasta_la_vista_money.budget.services.budget import BudgetService


class BudgetContainer(containers.DeclarativeContainer):
    expense = providers.DependenciesContainer()
    income = providers.DependenciesContainer()

    planning_repository = providers.Singleton(PlanningRepository)
    date_list_repository = providers.Singleton(DateListRepository)

    budget_service = providers.Factory(
        BudgetService,
        expense_repository=expense.expense_repository,
        income_repository=income.income_repository,
        planning_repository=planning_repository,
    )
