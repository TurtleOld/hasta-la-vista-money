"""Dependency injection container for users application."""

from dependency_injector import containers, providers
from django.conf import settings

from core.services.external_model import ExternalModelTransport
from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
    TransferMoneyLogRepository,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.users.protocols.services import (
    AccountingControlServiceProtocol,
    BankStatementImportServiceProtocol,
    BankStatementReconciliationServiceProtocol,
    BankStatementRetentionServiceProtocol,
    StatementCoverageServiceProtocol,
    StatementMarkupServiceProtocol,
    StatementRowLinkServiceProtocol,
    UserStatisticsServiceProtocol,
)
from hasta_la_vista_money.users.repositories.statement_coverage_repository import (  # noqa: E501
    StatementCoverageRepository,
)
from hasta_la_vista_money.users.repositories.statement_row_repository import (
    StatementRowRepository,
)
from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.services.accounting_control import (
    AccountingControlService,
)
from hasta_la_vista_money.users.services.bank_statement_import import (
    BankStatementImportService,
)
from hasta_la_vista_money.users.services.bank_statement_reconciliation import (
    BankStatementReconciliationService,
)
from hasta_la_vista_money.users.services.bank_statement_retention import (
    BankStatementRetentionService,
)
from hasta_la_vista_money.users.services.category_classifier import (
    CategoryClassifier,
    ExternalModelCategoryClassifier,
    NoopClassifier,
)
from hasta_la_vista_money.users.services.statement_coverage import (
    StatementCoverageService,
)
from hasta_la_vista_money.users.services.statement_identity import (
    StatementIdentityService,
)
from hasta_la_vista_money.users.services.statement_markup import (
    StatementMarkupService,
)
from hasta_la_vista_money.users.services.statement_row_links import (
    StatementRowLinkService,
)
from hasta_la_vista_money.users.services.statistics import (
    UserStatisticsService,
)


def _build_classifier() -> CategoryClassifier:
    """Собрать экземпляр категоризатора на основе настроек Django.

    Returns:
        ``ExternalModelCategoryClassifier`` если
        ``BANK_STATEMENT_CATEGORY_MODEL_BASE_URL`` задан, иначе
        ``NoopClassifier``.
    """
    base_url = getattr(
        settings,
        'BANK_STATEMENT_CATEGORY_MODEL_BASE_URL',
        '',
    ) or getattr(settings, 'CATEGORY_CLASSIFIER_BASE_URL', '')
    if not base_url:
        return NoopClassifier()
    transport = ExternalModelTransport(
        base_url=base_url,
        api_key=getattr(
            settings,
            'BANK_STATEMENT_CATEGORY_MODEL_API_KEY',
            '',
        )
        or getattr(settings, 'CATEGORY_CLASSIFIER_API_KEY', ''),
        model=getattr(
            settings,
            'BANK_STATEMENT_CATEGORY_MODEL_NAME',
            '',
        )
        or getattr(settings, 'CATEGORY_CLASSIFIER_MODEL', ''),
    )
    return ExternalModelCategoryClassifier(
        transport=transport,
    )


class UsersContainer(containers.DeclarativeContainer):
    """DI-контейнер для приложения users."""

    statistics_repository = providers.Singleton(StatisticsRepository)

    user_statistics_service: providers.Factory[
        UserStatisticsServiceProtocol
    ] = providers.Factory(
        UserStatisticsService,
        statistics_repository=statistics_repository,
    )

    category_classifier = providers.Singleton(_build_classifier)

    statement_identity_service = providers.Factory(StatementIdentityService)

    bank_statement_reconciliation_service: providers.Factory[
        BankStatementReconciliationServiceProtocol
    ] = providers.Factory(
        BankStatementReconciliationService,
        balance_service=providers.Factory(BalanceService),
    )

    statement_row_repository = providers.Singleton(StatementRowRepository)
    statement_coverage_repository = providers.Singleton(
        StatementCoverageRepository,
    )

    statement_coverage_service: providers.Factory[
        StatementCoverageServiceProtocol
    ] = providers.Factory(
        StatementCoverageService,
        coverage_repository=statement_coverage_repository,
    )

    accounting_control_service: providers.Factory[
        AccountingControlServiceProtocol
    ] = providers.Factory(
        AccountingControlService,
        coverage_service=statement_coverage_service,
    )

    statement_row_link_service: providers.Factory[
        StatementRowLinkServiceProtocol
    ] = providers.Factory(
        StatementRowLinkService,
        statement_row_repository=statement_row_repository,
        reconciliation_service=bank_statement_reconciliation_service,
    )

    bank_statement_retention_service: providers.Factory[
        BankStatementRetentionServiceProtocol
    ] = providers.Factory(
        BankStatementRetentionService,
        reconciliation_service=bank_statement_reconciliation_service,
    )

    statement_markup_service: providers.Factory[
        StatementMarkupServiceProtocol
    ] = providers.Factory(
        StatementMarkupService,
        balance_service=providers.Factory(BalanceService),
        account_repository=providers.Singleton(AccountRepository),
        transfer_log_repository=providers.Singleton(
            TransferMoneyLogRepository,
        ),
        statement_row_repository=statement_row_repository,
    )

    bank_statement_import_service: providers.Factory[
        BankStatementImportServiceProtocol
    ] = providers.Factory(
        BankStatementImportService,
        classifier=category_classifier,
        account_repository=providers.Singleton(AccountRepository),
        statement_row_repository=statement_row_repository,
        identity_service=statement_identity_service,
        coverage_service=statement_coverage_service,
    )
