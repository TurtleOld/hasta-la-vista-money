from dependency_injector import containers, providers

from hasta_la_vista_money.receipts.protocols.services import (
    PendingReceiptServiceProtocol,
    ReceiptCreatorServiceProtocol,
    ReceiptImportServiceProtocol,
    ReceiptUpdaterServiceProtocol,
)
from hasta_la_vista_money.receipts.repositories import (
    ProductRepository,
    ReceiptRepository,
    SellerRepository,
)
from hasta_la_vista_money.receipts.services.pending_receipt_service import (
    PendingReceiptService,
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


class ReceiptsContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()
    finance_account = providers.DependenciesContainer()

    receipt_repository = providers.Singleton(ReceiptRepository)
    product_repository = providers.Singleton(ProductRepository)
    seller_repository = providers.Singleton(SellerRepository)

    receipt_creator_service: providers.Factory[
        ReceiptCreatorServiceProtocol
    ] = providers.Factory(
        ReceiptCreatorService,
        account_service=core.account_service,
        account_repository=finance_account.account_repository,
        product_repository=product_repository,
        receipt_repository=receipt_repository,
        seller_repository=seller_repository,
    )
    receipt_import_service: providers.Factory[ReceiptImportServiceProtocol] = (
        providers.Factory(
            ReceiptImportService,
            receipt_repository=receipt_repository,
            receipt_creator_service=receipt_creator_service,
        )
    )
    receipt_updater_service: providers.Factory[
        ReceiptUpdaterServiceProtocol
    ] = providers.Factory(
        ReceiptUpdaterService,
        account_service=core.account_service,
        account_repository=finance_account.account_repository,
        product_repository=product_repository,
        receipt_repository=receipt_repository,
        seller_repository=seller_repository,
    )
    pending_receipt_service: providers.Factory[
        PendingReceiptServiceProtocol
    ] = providers.Factory(
        PendingReceiptService,
        receipt_creator_service=receipt_creator_service,
        receipt_repository=receipt_repository,
    )
