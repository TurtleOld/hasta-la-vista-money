"""Dependency injection container для users приложения."""

from dependency_injector import containers, providers

from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.services.statistics import (
    UserStatisticsService,
)


class UsersContainer(containers.DeclarativeContainer):
    """Контейнер для users приложения.

    Регистрирует репозитории и сервисы для работы с пользователями.
    """

    statistics_repository = providers.Singleton(StatisticsRepository)

    user_statistics_service = providers.Factory(
        UserStatisticsService,
        statistics_repository=statistics_repository,
    )
