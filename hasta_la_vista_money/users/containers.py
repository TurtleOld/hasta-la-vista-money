"""Dependency injection container for users application."""

from dependency_injector import containers, providers
from django.conf import settings

from core.services.external_model import ExternalModelTransport
from hasta_la_vista_money.users.protocols.services import (
    BankStatementReconciliationServiceProtocol,
    BankStatementRetentionServiceProtocol,
    UserStatisticsServiceProtocol,
)
from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
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

    bank_statement_reconciliation_service: providers.Factory[
        BankStatementReconciliationServiceProtocol
    ] = providers.Factory(BankStatementReconciliationService)

    bank_statement_retention_service: providers.Factory[
        BankStatementRetentionServiceProtocol
    ] = providers.Factory(
        BankStatementRetentionService,
        reconciliation_service=bank_statement_reconciliation_service,
    )
