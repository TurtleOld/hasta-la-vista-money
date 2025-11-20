"""Test helpers for finance account tests."""

from django.http import HttpRequest

from config.containers import ApplicationContainer


def setup_container_for_request(request: HttpRequest) -> None:
    """Устанавливает контейнер DI на request для тестов.

    Args:
        request: HTTP request объект для установки контейнера.
    """
    if not hasattr(request, 'container'):
        container = ApplicationContainer()
        request.container = container

