from dependency_injector import containers, providers
from openai import OpenAI

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.budget.containers import BudgetContainer
from hasta_la_vista_money.expense.containers import ExpenseContainer
from hasta_la_vista_money.finance_account.containers import (
    FinanceAccountContainer,
)
from hasta_la_vista_money.income.containers import IncomeContainer
from hasta_la_vista_money.loan.containers import LoanContainer
from hasta_la_vista_money.receipts.containers import ReceiptsContainer


class CoreContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    openai_client = providers.Singleton(
        OpenAI,
        base_url=config.openai.base_url,
        api_key=config.openai.api_key,
    )

    account_service = providers.Dependency(instance_of=AccountServiceProtocol)


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    core = providers.Container(
        CoreContainer,
        config=config.core,
    )

    receipts = providers.Container(
        ReceiptsContainer,
        core=core,
        finance_account=providers.DependenciesContainer(),
    )

    income = providers.Container(
        IncomeContainer,
        core=core,
    )

    expense = providers.Container(
        ExpenseContainer,
        core=core,
        finance_account=providers.DependenciesContainer(),
        receipts=receipts,
    )

    finance_account = providers.Container(
        FinanceAccountContainer,
        core=core,
        expense=expense,
        income=income,
        receipts=receipts,
    )

    core.account_service.override(finance_account.account_service)

    receipts.finance_account.override(finance_account)
    expense.finance_account.override(finance_account)

    budget = providers.Container(
        BudgetContainer,
        expense=expense,
        income=income,
    )

    loan = providers.Container(LoanContainer)
