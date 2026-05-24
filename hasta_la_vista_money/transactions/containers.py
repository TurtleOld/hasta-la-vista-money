"""Dependency injection container for the transactions app."""

from dependency_injector import containers, providers

from hasta_la_vista_money.transactions.protocols.services import (
    TransactionServiceProtocol,
)
from hasta_la_vista_money.transactions.repositories import (
    CategoryRepository,
    TransactionRepository,
)
from hasta_la_vista_money.transactions.services.category_ops import (
    CategoryService,
)
from hasta_la_vista_money.transactions.services.transaction_ops import (
    TransactionService,
)


class TransactionContainer(containers.DeclarativeContainer):
    """DI container exposing transaction repositories and services."""

    core = providers.DependenciesContainer()

    transaction_repository = providers.Singleton(TransactionRepository)
    category_repository = providers.Singleton(CategoryRepository)

    category_service = providers.Factory(
        CategoryService,
        category_repository=category_repository,
    )

    transaction_service: providers.Singleton[TransactionServiceProtocol] = (
        providers.Singleton(
            TransactionService,
            account_service=core.account_service,
            transaction_repository=transaction_repository,
        )
    )
