from dependency_injector import containers, providers

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.finance_account.page_context_service import (
    AccountPageContextService,
)
from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
    TransferMoneyLogRepository,
)
from hasta_la_vista_money.finance_account.services import (
    AccountService,
    TransferService,
)


class FinanceAccountContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()
    expense = providers.DependenciesContainer()
    income = providers.DependenciesContainer()
    receipts = providers.DependenciesContainer()

    account_repository = providers.Singleton(AccountRepository)
    transfer_money_log_repository = providers.Singleton(
        TransferMoneyLogRepository,
    )

    account_service: providers.Factory[AccountServiceProtocol] = (
        providers.Factory(
            AccountService,
            account_repository=account_repository,
            transfer_money_log_repository=transfer_money_log_repository,
            expense_repository=expense.expense_repository,
            income_repository=income.income_repository,
            receipt_repository=receipts.receipt_repository,
        )
    )
    transfer_service = providers.Factory(
        TransferService,
        transfer_money_log_repository=transfer_money_log_repository,
    )
    account_page_context_service = providers.Factory(
        AccountPageContextService,
        account_repository=account_repository,
        transfer_money_log_repository=transfer_money_log_repository,
        account_service=account_service,
        transfer_service=transfer_service,
    )
