"""System health and readiness views."""

from pathlib import Path

from django.contrib.staticfiles import finders
from django.core.cache import cache
from django.db import connection
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from hasta_la_vista_money import constants
from hasta_la_vista_money.system.services.pwa import get_pwa_precache_payload


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


@method_decorator(never_cache, name='dispatch')
class ServiceWorkerView(View):
    http_method_names = ['get', 'head', 'options']

    def get(self, request: HttpRequest) -> HttpResponse:
        del request
        sw_path = finders.find('sw.js')
        if not sw_path:
            raise Http404
        response = HttpResponse(
            Path(sw_path).read_bytes(),
            content_type='application/javascript',
        )
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Service-Worker-Allowed'] = '/'
        return response


@method_decorator(never_cache, name='dispatch')
class ServiceWorkerPrecacheView(View):
    http_method_names = ['get', 'head', 'options']

    def get(self, request: HttpRequest) -> JsonResponse:
        del request
        return JsonResponse(get_pwa_precache_payload())


@method_decorator(never_cache, name='dispatch')
class OfflineView(TemplateView):
    template_name = 'system/offline.html'
