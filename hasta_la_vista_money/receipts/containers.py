from dependency_injector import containers, providers

from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreatorService,
)
from hasta_la_vista_money.receipts.services.receipt_import import (
    ReceiptImportService,
)
from hasta_la_vista_money.receipts.services.receipt_updater import (
    ReceiptUpdaterService,
)


class ReceiptsContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()

    receipt_creator_service = providers.Factory(
        ReceiptCreatorService,
        account_service=core.account_service,
    )
    receipt_import_service = providers.Factory(ReceiptImportService)
    receipt_updater_service = providers.Factory(
        ReceiptUpdaterService,
        account_service=core.account_service,
    )
