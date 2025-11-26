"""Общие helper-функции для тестов с поддержкой DI контейнеров."""

from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

from dependency_injector import providers
from django.http import HttpRequest

from config.containers import ApplicationContainer
from core.protocols.services import AccountServiceProtocol

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


def setup_container_for_request(
    request: HttpRequest,
) -> ApplicationContainer:
    """Устанавливает контейнер DI на request для тестов.

    Args:
        request: HTTP request объект для установки контейнера.

    Returns:
        ApplicationContainer: Созданный или существующий контейнер.
    """
    request_with_container = cast('RequestWithContainer', request)
    if not hasattr(request_with_container, 'container'):
        container = ApplicationContainer()
        request_with_container.container = container
        return container
    return request_with_container.container


def create_test_container_with_mock_account_service(
    mock_account_service: MagicMock | None = None,
) -> ApplicationContainer:
    """Создает тестовый контейнер с моком AccountService.

    Args:
        mock_account_service: Опциональный мок AccountService.
            Если не передан, создается автоматически.

    Returns:
        ApplicationContainer: Контейнер с переопределенным AccountService.
    """
    container = ApplicationContainer()
    if mock_account_service is None:
        mock_account_service = MagicMock(spec=AccountServiceProtocol)
    container.core.account_service.override(
        providers.Object(mock_account_service),
    )
    return container


def reset_container_overrides(container: ApplicationContainer) -> None:
    """Сбрасывает все переопределения в контейнере.

    Args:
        container: Контейнер для сброса переопределений.
    """
    container.core.account_service.reset_override()
