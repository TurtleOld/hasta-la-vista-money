from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from django.http import HttpRequest, HttpResponse

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
        return self.get_response(request_with_container)
