from dependency_injector import containers, providers

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.budget.containers import BudgetContainer
from hasta_la_vista_money.finance_account.containers import (
    FinanceAccountContainer,
)
from hasta_la_vista_money.loan.containers import LoanContainer
from hasta_la_vista_money.receipts.containers import ReceiptsContainer
from hasta_la_vista_money.transactions.containers import TransactionContainer
from hasta_la_vista_money.users.containers import UsersContainer


class CoreContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    account_service: providers.Dependency[AccountServiceProtocol] = (
        providers.Dependency()
    )


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

    transactions = providers.Container(
        TransactionContainer,
        core=core,
    )

    finance_account = providers.Container(
        FinanceAccountContainer,
        core=core,
        receipts=receipts,
        transactions=transactions,
    )

    core.account_service.override(finance_account.account_service)

    receipts.finance_account.override(finance_account)

    budget = providers.Container(
        BudgetContainer,
        transactions=transactions,
    )

    loan = providers.Container(LoanContainer)

    users = providers.Container(UsersContainer)
