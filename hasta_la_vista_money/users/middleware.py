from collections.abc import Callable

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone

from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.timezones import get_available_timezones


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
            allowed_prefixes = tuple(
                prefix
                for prefix in (settings.STATIC_URL, settings.MEDIA_URL)
                if prefix
            )
            if (
                request.path not in allowed_paths
                and not request.path.startswith(allowed_prefixes)
            ):
                return redirect('users:registration')
        return self.get_response(request)


class UserTimezoneMiddleware:
    """Activate the viewing user's IANA timezone for the request.

    Anonymous users and users with a corrupted stored value fall back to
    the global application timezone (``settings.TIME_ZONE``), so a bad
    saved value never breaks a request.
    """

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tz_name = settings.TIME_ZONE
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            candidate = getattr(user, 'timezone_name', '') or ''
            if candidate in get_available_timezones():
                tz_name = candidate
        timezone.activate(tz_name)
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
