"""Admin mixin that keeps money changes inside the balance service."""

from django.http import HttpRequest


class MovementAdminMixin:
    """Forbid adding and deleting movements in admin."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        del request
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: object | None = None,
    ) -> bool:
        del request, obj
        return False
