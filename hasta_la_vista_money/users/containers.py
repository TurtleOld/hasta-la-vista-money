"""Dependency injection container for users application.

This module provides DI container configuration for user-related
repositories and services.
"""

from dependency_injector import containers, providers

from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.services.statistics import (
    UserStatisticsService,
)


class UsersContainer(containers.DeclarativeContainer):
    """Dependency injection container for users application.

    Registers repositories and services for working with users.
    """

    statistics_repository = providers.Singleton(StatisticsRepository)

    user_statistics_service = providers.Factory(
        UserStatisticsService,
        statistics_repository=statistics_repository,
    )
