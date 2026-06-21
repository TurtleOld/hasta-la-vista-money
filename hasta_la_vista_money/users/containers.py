"""Dependency injection container for users application."""

from dependency_injector import containers, providers
from django.conf import settings

from hasta_la_vista_money.users.protocols.services import (
    UserStatisticsServiceProtocol,
)
from hasta_la_vista_money.users.repositories.statistics_repository import (
    StatisticsRepository,
)
from hasta_la_vista_money.users.services.category_classifier import (
    NoopClassifier,
    OpenAICompatibleClassifier,
)
from hasta_la_vista_money.users.services.statistics import (
    UserStatisticsService,
)


def _build_classifier():
    """Собрать экземпляр категоризатора на основе настроек Django.

    Returns:
        ``OpenAICompatibleClassifier`` если ``CATEGORY_CLASSIFIER_BASE_URL``
        задан, иначе ``NoopClassifier``.
    """
    base_url = getattr(settings, 'CATEGORY_CLASSIFIER_BASE_URL', '')
    if not base_url:
        return NoopClassifier()
    return OpenAICompatibleClassifier(
        base_url=base_url,
        api_key=getattr(settings, 'CATEGORY_CLASSIFIER_API_KEY', ''),
        model=getattr(settings, 'CATEGORY_CLASSIFIER_MODEL', ''),
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
