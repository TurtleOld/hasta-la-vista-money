"""Dependency injection container for users application."""

from dependency_injector import containers, providers

from hasta_la_vista_money.finance_account.repositories import (
    AccountRepository,
    TransferMoneyLogRepository,
)
from hasta_la_vista_money.finance_account.services.balance_service import (
    BalanceService,
)
from hasta_la_vista_money.users.protocols.services import (
    AccountingProblemServiceProtocol,
    BankStatementImportServiceProtocol,
    BankStatementReconciliationServiceProtocol,
    BankStatementRetentionServiceProtocol,
    StatementIdentityServiceProtocol,
    StatementMarkupServiceProtocol,
    StatementRowLinkServiceProtocol,
    UserStatisticsServiceProtocol,
)
from hasta_la_vista_money.users.repositories.accounting_problem_repository import (  # noqa: E501
    AccountingProblemRepository,
)
from hasta_la_vista_money.users.repositories.statement_identity_repository import (  # noqa: E501
    StatementIdentityRepository,
)
from hasta_la_vista_money.users.repositories.statement_row_repository import (
    StatementRowRepository,
)
from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.services.accounting_problem_service import (
    AccountingProblemService,
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
    LocalCategoryClassifier,
)
from hasta_la_vista_money.users.services.statement_id_fingerprint import (
    StatementIdFingerprintService,
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
    """Build the local-only bank statement categorizer.

    Bank statements are classified exclusively by local rules: an existing
    user category named in the operation description, otherwise manual
    markup. No external model is configured or called.
    """
    return LocalCategoryClassifier()


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

    statement_row_repository = providers.Singleton(StatementRowRepository)

    accounting_problem_repository = providers.Singleton(
        AccountingProblemRepository,
    )

    accounting_problem_service: providers.Factory[
        AccountingProblemServiceProtocol
    ] = providers.Factory(
        AccountingProblemService,
        repository=accounting_problem_repository,
    )

    statement_identity_repository = providers.Singleton(
        StatementIdentityRepository,
    )

    statement_identity_service: providers.Factory[
        StatementIdentityServiceProtocol
    ] = providers.Factory(
        StatementIdentityService,
        fingerprint_service=providers.Factory(StatementIdFingerprintService),
        repository=statement_identity_repository,
    )

    bank_statement_reconciliation_service: providers.Factory[
        BankStatementReconciliationServiceProtocol
    ] = providers.Factory(
        BankStatementReconciliationService,
        statement_row_repository=statement_row_repository,
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
        identity_service=statement_identity_service,
        identity_repository=statement_identity_repository,
    )
