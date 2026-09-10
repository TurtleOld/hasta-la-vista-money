"""Middleware giving every HTTP request a default audit operation id."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from hasta_la_vista_money.system.services.audit_context import audit_operation


class AuditOperationMiddleware:
    """Safety net for model saves that bypass the service layer.

    Forms that save a model directly, past the service layer's own
    ``audit_operation(kind=...)`` call, would otherwise leave their audit
    entries without an ``operation_id``. Wrapping the whole request in one
    here still lets a service-layer context override it for its own block.
    """

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with audit_operation():
            return self.get_response(request)
