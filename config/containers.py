from dependency_injector import containers, providers

from core.protocols.services import AccountServiceProtocol
from hasta_la_vista_money.expense.protocols.services import (
    ExpenseServiceProtocol,
)
from hasta_la_vista_money.expense.services.expense_services import (
    ExpenseService,
)
from hasta_la_vista_money.finance_account.services import AccountService
from hasta_la_vista_money.receipts.protocols.services import (
    ReceiptCreatorServiceProtocol,
    ReceiptImportServiceProtocol,
    ReceiptUpdaterServiceProtocol,
)
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreatorService,
)
from hasta_la_vista_money.receipts.services.receipt_import import (
    ReceiptImportService,
)
from hasta_la_vista_money.receipts.services.receipt_updater import (
    ReceiptUpdaterService,
)


class CoreContainer(containers.DeclarativeContainer):
    account_service: providers.Factory[AccountServiceProtocol] = (
        providers.Factory(
            AccountService,
        )
    )


class ApplicationContainer(containers.DeclarativeContainer):
    config = providers.Configuration()

    core = providers.Container(CoreContainer)

    account_service: providers.Factory[AccountServiceProtocol] = (
        core.account_service
    )

    expense_service: providers.Factory[ExpenseServiceProtocol] = (
        providers.Factory(
            ExpenseService,
        )
    )

    receipt_creator_service: providers.Factory[
        ReceiptCreatorServiceProtocol
    ] = providers.Factory(
        ReceiptCreatorService,
    )

    receipt_updater_service: providers.Factory[
        ReceiptUpdaterServiceProtocol
    ] = providers.Factory(
        ReceiptUpdaterService,
    )

    receipt_import_service: providers.Factory[ReceiptImportServiceProtocol] = (
        providers.Factory(
            ReceiptImportService,
        )
    )
