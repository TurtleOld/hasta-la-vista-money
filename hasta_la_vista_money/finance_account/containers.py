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
    BalanceTrendService,
    TransferService,
)


class FinanceAccountContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()
    receipts = providers.DependenciesContainer()
    transactions = providers.DependenciesContainer()

    account_repository = providers.Singleton(AccountRepository)
    transfer_money_log_repository = providers.Singleton(
        TransferMoneyLogRepository,
    )

    account_service: providers.Factory[AccountServiceProtocol] = (
        providers.Factory(
            AccountService,
            account_repository=account_repository,
            transfer_money_log_repository=transfer_money_log_repository,
            transaction_repository=transactions.transaction_repository,
            receipt_repository=receipts.receipt_repository,
        )
    )
    transfer_service = providers.Factory(
        TransferService,
        transfer_money_log_repository=transfer_money_log_repository,
    )
    balance_trend_service = providers.Factory(BalanceTrendService)
    account_page_context_service = providers.Factory(
        AccountPageContextService,
        account_repository=account_repository,
        transfer_money_log_repository=transfer_money_log_repository,
        account_service=account_service,
        transfer_service=transfer_service,
        balance_trend_service=balance_trend_service,
    )
