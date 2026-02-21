from collections.abc import Callable

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy

from hasta_la_vista_money.users.models import User


class CheckAdminMiddleware:
    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        """init."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        has_superuser = cache.get('has_superuser')
        if has_superuser is None:
            has_superuser = User.objects.filter(is_superuser=True).exists()
            cache.set('has_superuser', has_superuser, 300)

        if not has_superuser:
            allowed_paths = {
                str(reverse_lazy('users:registration')),
                str(reverse_lazy('login')),
            }
            if request.path not in allowed_paths:
                return redirect('users:registration')
        return self.get_response(request)
