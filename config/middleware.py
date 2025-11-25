from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from config.containers import ApplicationContainer


class CoreMiddleware:
    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        self.get_response = get_response
        self.container = ApplicationContainer()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.container = self.container
        return self.get_response(request)
