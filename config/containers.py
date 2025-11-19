from dependency_injector import containers, providers
from openai import OpenAI

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.expense.containers import ExpenseContainer
from hasta_la_vista_money.finance_account.containers import (
    FinanceAccountContainer,
)
from hasta_la_vista_money.finance_account.services import AccountService
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

    account_service: providers.Factory[AccountServiceProtocol] = (
        providers.Factory(
            AccountService,
        )
    )


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    core = providers.Container(
        CoreContainer,
        config=config.core,
    )

    expense = providers.Container(
        ExpenseContainer,
        core=core,
    )

    income = providers.Container(
        IncomeContainer,
        core=core,
    )

    receipts = providers.Container(
        ReceiptsContainer,
        core=core,
    )

    finance_account = providers.Container(
        FinanceAccountContainer,
        core=core,
    )

    loan = providers.Container(LoanContainer)
