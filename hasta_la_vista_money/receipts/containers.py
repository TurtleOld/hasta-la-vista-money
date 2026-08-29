from typing import TYPE_CHECKING, cast

from dependency_injector import containers, providers
from django.conf import settings

from core.services.external_model import ExternalModelTransport
from hasta_la_vista_money.receipts.protocols.services import (
    ExternalProductCategoryServiceProtocol,
    PendingReceiptServiceProtocol,
    ProductCategoryCorrectionServiceProtocol,
    ReceiptCreatorServiceProtocol,
    ReceiptDeleterServiceProtocol,
    ReceiptProcessingServiceProtocol,
    ReceiptUpdaterServiceProtocol,
)
from hasta_la_vista_money.receipts.repositories import (
    ProductCategoryRepository,
    ProductNameCategoryMappingRepository,
    ProductRepository,
    ReceiptProcessingLogRepository,
    ReceiptRepository,
    SellerRepository,
)
from hasta_la_vista_money.receipts.services.category_classifier import (
    ReceiptItemCategoryService,
    build_embedding_provider,
)
from hasta_la_vista_money.receipts.services.external_category import (
    ExternalProductCategoryService,
)
from hasta_la_vista_money.receipts.services.pending_receipt_service import (
    PendingReceiptService,
)
from hasta_la_vista_money.receipts.services.product_categories import (
    ProductCategoryService,
)
from hasta_la_vista_money.receipts.services.product_category_correction import (
    ProductCategoryCorrectionService,
)
from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreatorService,
)
from hasta_la_vista_money.receipts.services.receipt_deleter import (
    ReceiptDeleterService,
)
from hasta_la_vista_money.receipts.services.receipt_processing_service import (
    ReceiptProcessingService,
)
from hasta_la_vista_money.receipts.services.receipt_updater import (
    ReceiptUpdaterService,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _build_category_model_transport() -> ExternalModelTransport | None:
    """Build the optional transport for receipt product categorization."""
    base_url = getattr(settings, 'RECEIPT_CATEGORY_MODEL_BASE_URL', '')
    if not base_url:
        return None
    return ExternalModelTransport(
        base_url=base_url,
        api_key=getattr(settings, 'RECEIPT_CATEGORY_MODEL_API_KEY', ''),
        model=getattr(settings, 'RECEIPT_CATEGORY_MODEL_NAME', ''),
    )


class ReceiptsContainer(containers.DeclarativeContainer):
    core = providers.DependenciesContainer()
    finance_account = providers.DependenciesContainer()

    receipt_repository = providers.Singleton(ReceiptRepository)
    product_category_repository = providers.Singleton(ProductCategoryRepository)
    product_name_category_mapping_repository = providers.Singleton(
        ProductNameCategoryMappingRepository,
    )
    product_repository = providers.Singleton(ProductRepository)
    seller_repository = providers.Singleton(SellerRepository)
    receipt_processing_log_repository = providers.Singleton(
        ReceiptProcessingLogRepository,
    )
    category_model_transport = providers.Singleton(
        _build_category_model_transport,
    )
    embedding_provider = providers.Singleton(build_embedding_provider)
    receipt_item_category_service = providers.Factory(
        ReceiptItemCategoryService,
        embedding_provider=embedding_provider,
    )
    product_category_correction_service: providers.Factory[
        ProductCategoryCorrectionServiceProtocol
    ] = providers.Factory(
        ProductCategoryCorrectionService,
        mapping_repository=product_name_category_mapping_repository,
        product_repository=product_repository,
    )
    external_product_category_service: providers.Factory[
        ExternalProductCategoryServiceProtocol
    ] = providers.Factory(
        ExternalProductCategoryService,
        transport=category_model_transport,
        product_category_repository=product_category_repository,
    )

    receipt_creator_service: providers.Factory[
        ReceiptCreatorServiceProtocol
    ] = providers.Factory(
        ReceiptCreatorService,
        account_service=core.account_service,
        account_repository=finance_account.account_repository,
        product_category_repository=product_category_repository,
        product_repository=product_repository,
        receipt_repository=receipt_repository,
        seller_repository=seller_repository,
    )
    product_category_service = providers.Factory(
        ProductCategoryService,
        product_category_repository=product_category_repository,
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
        category_correction_service=product_category_correction_service,
    )
    receipt_deleter_service: providers.Factory[
        ReceiptDeleterServiceProtocol
    ] = providers.Factory(
        ReceiptDeleterService,
        account_service=core.account_service,
    )
    receipt_processing_service: providers.Factory[
        ReceiptProcessingServiceProtocol
    ] = providers.Factory(
        cast(
            'Callable[..., ReceiptProcessingServiceProtocol]',
            ReceiptProcessingService,
        ),
        receipt_creator_service=receipt_creator_service,
        processing_log_repository=receipt_processing_log_repository,
    )
    pending_receipt_service: providers.Factory[
        PendingReceiptServiceProtocol
    ] = providers.Factory(
        cast(
            'Callable[..., PendingReceiptServiceProtocol]',
            PendingReceiptService,
        ),
        receipt_creator_service=receipt_creator_service,
        receipt_repository=receipt_repository,
    )
