"""Shared base views used across multiple apps."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.db import connection, models
from django.forms import BaseForm
from django.http import HttpRequest, JsonResponse
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.generic import CreateView, UpdateView
from django_filters.views import FilterView

from hasta_la_vista_money import constants


@method_decorator(never_cache, name='dispatch')
class HealthCheckView(View):
    """Liveness probe that does not touch external dependencies."""

    http_method_names = ['get', 'head', 'options']

    def get(self, request: HttpRequest) -> JsonResponse:
        del request
        return JsonResponse({'status': 'ok'})


@method_decorator(never_cache, name='dispatch')
class ReadinessCheckView(View):
    """Readiness probe with database and cache checks."""

    http_method_names = ['get', 'head', 'options']

    def get(self, request: HttpRequest) -> JsonResponse:
        del request
        checks = {
            'database': self._database_is_ready(),
            'cache': self._cache_is_ready(),
        }
        is_ready = all(checks.values())
        status_code = 200 if is_ready else 503
        return JsonResponse(
            {
                'status': 'ok' if is_ready else 'unavailable',
                'checks': checks,
            },
            status=status_code,
        )

    def _database_is_ready(self) -> bool:
        try:
            connection.ensure_connection()
        except Exception:
            return False
        return True

    def _cache_is_ready(self) -> bool:
        try:
            cache_key = 'readiness-check'
            cache.set(cache_key, 'ok', timeout=constants.THIRTY)
            return cache.get(cache_key) == 'ok'
        except Exception:
            return False


class BaseEntityFilterView(
    LoginRequiredMixin,
    SuccessMessageMixin[BaseForm],
    FilterView,
):
    """Common configuration for entity filter views."""

    paginate_by: int | None = constants.PAGINATE_BY_DEFAULT
    no_permission_url = reverse_lazy('login')


class BaseEntityCreateView[  # type: ignore[misc]
    ModelType: models.Model,
    FormType,
](
    LoginRequiredMixin,
    SuccessMessageMixin[BaseForm],
    CreateView[ModelType, FormType],  # type: ignore[type-var]
):
    """Base class for creating entities.

    Provides common configuration for entity creation views,
    including authentication, success messages, and permission handling.
    """

    no_permission_url = reverse_lazy('login')


class BaseEntityUpdateView[  # type: ignore[misc]
    ModelType: models.Model,
    FormType,
](
    LoginRequiredMixin,
    SuccessMessageMixin[BaseForm],
    UpdateView[ModelType, FormType],  # type: ignore[type-var]
):
    """Base class for updating entities.

    Provides common configuration for entity update views,
    including authentication, success messages, and permission handling.
    """

    no_permission_url = reverse_lazy('login')
