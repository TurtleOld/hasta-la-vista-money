from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from django.http import HttpRequest, HttpResponse
from structlog.contextvars import get_contextvars

from config.containers import ApplicationContainer

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import RequestWithContainer


class CoreMiddleware:
    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        self.get_response = get_response
        self.container = ApplicationContainer()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_with_container = cast('RequestWithContainer', request)
        request_with_container.container = self.container
        response = self.get_response(request_with_container)
        context = get_contextvars()
        request_id = context.get('request_id') or context.get('correlation_id')
        if request_id is not None:
            response['X-Request-ID'] = str(request_id)
        return response
