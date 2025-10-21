from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse_lazy

from hasta_la_vista_money.users.models import User


class CheckAdminMiddleware:
    def __init__(self, get_response):
        """init."""
        self.get_response = get_response

    def __call__(self, request):
        has_superuser = cache.get('has_superuser')
        if has_superuser is None:
            has_superuser = User.objects.filter(is_superuser=True).exists()
            cache.set('has_superuser', has_superuser, 300)

        if not has_superuser and request.path != reverse_lazy(
            'users:registration',
        ):
            return redirect('users:registration')
        return self.get_response(request)
