from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from config.containers import ApplicationContainer


class CoreMiddleware:
    container: ApplicationContainer = ApplicationContainer()

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.container = self.container
        return self.get_response(request)
