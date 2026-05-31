"""System health and readiness views."""

from pathlib import Path

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.staticfiles import finders
from django.core.cache import cache
from django.db import connection
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.generic import ListView, TemplateView

from hasta_la_vista_money import constants
from hasta_la_vista_money.system.models import AuditLog
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


AUDIT_PAGE_SIZE = 30

AUDITED_MODEL_CHOICES = [
    ('', 'Все модели'),
    ('finance_account.Transaction', 'Транзакции'),
    ('receipts.Receipt', 'Чеки'),
    ('finance_account.TransferMoneyLog', 'Переводы'),
    ('finance_account.Account', 'Счета'),
]


class AuditLogView(LoginRequiredMixin, ListView):
    template_name = 'system/auditlog.html'
    context_object_name = 'entries'
    paginate_by = AUDIT_PAGE_SIZE

    def get_queryset(self):
        qs = AuditLog.objects.filter(
            user=self.request.user,
        ).select_related('user')
        model = self.request.GET.get('model', '')
        date_from = self.request.GET.get('date_from', '')
        date_to = self.request.GET.get('date_to', '')
        action = self.request.GET.get('action', '')
        if model:
            qs = qs.filter(model_name=model)
        if action:
            qs = qs.filter(action=action)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['model_choices'] = AUDITED_MODEL_CHOICES
        ctx['action_choices'] = AuditLog.Action.choices
        ctx['filter'] = {
            'model': self.request.GET.get('model', ''),
            'action': self.request.GET.get('action', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
        }
        return ctx
