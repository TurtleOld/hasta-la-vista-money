import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404
from django.urls import include, path, re_path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from hasta_la_vista_money.finance_account.views import (
    FinancesCategoryView,
    FinancesCreateView,
    FinancesView,
)
from hasta_la_vista_money.system.views import (
    HealthCheckView,
    OfflineView,
    ReadinessCheckView,
    ServiceWorkerPrecacheView,
    ServiceWorkerView,
)
from hasta_la_vista_money.users.views import (
    IndexView,
    LoginUser,
    LogoutUser,
)


def _serve_file(
    file_path: Path,
    content_type: str | None = None,
) -> FileResponse:
    if not file_path.exists() or file_path.is_dir():
        raise Http404

    guessed_content_type, encoding = mimetypes.guess_type(file_path.name)
    response = FileResponse(
        file_path.open('rb'),
        content_type=content_type or 'application/octet-stream',
    )
    if content_type is None:
        response['Content-Type'] = (
            guessed_content_type or 'application/octet-stream'
        )
    stat_result = file_path.stat()
    response['Content-Length'] = str(stat_result.st_size)
    if encoding:
        response['Content-Encoding'] = encoding
    return response


def debug_media_serve(request, path: str):
    del request
    media_root = Path(settings.MEDIA_ROOT)
    file_path = (media_root / path).resolve()
    if (
        media_root.resolve() not in file_path.parents
        and file_path != media_root.resolve()
    ):
        raise Http404
    return _serve_file(file_path)


def debug_static_serve(request, path: str):
    del request
    static_file = finders.find(path)
    if not static_file:
        raise Http404
    if path.endswith('.webmanifest'):
        content_type = 'application/manifest+json'
    else:
        content_type = None
    return _serve_file(Path(static_file), content_type=content_type)


urlpatterns = [
    path('healthz/', HealthCheckView.as_view(), name='healthz'),
    path('readyz/', ReadinessCheckView.as_view(), name='readyz'),
    path('sw.js', ServiceWorkerView.as_view(), name='service_worker'),
    path(
        'sw-precache.json',
        ServiceWorkerPrecacheView.as_view(),
        name='service_worker_precache',
    ),
    path('offline/', OfflineView.as_view(), name='offline'),
    re_path(
        r'^users/',
        include(
            'hasta_la_vista_money.users.urls',
            namespace='users',
        ),
    ),
    path('', IndexView.as_view(), name='index'),
    path(
        'login/',
        LoginUser.as_view(redirect_authenticated_user=True),
        name='login',
    ),
    path(
        'logout/',
        LogoutUser.as_view(),
        {'next_page': settings.LOGOUT_REDIRECT_URL},
        name='logout',
    ),
    path(
        'authentication/',
        include(
            'hasta_la_vista_money.authentication.urls',
            namespace='authentication',
        ),
    ),
    path(
        'finance_account/',
        include(
            'hasta_la_vista_money.finance_account.urls',
            namespace='finance_account',
        ),
    ),
    path('finance/', FinancesView.as_view(), name='finances'),
    path(
        'finance/categories/',
        FinancesCategoryView.as_view(),
        name='finances_categories',
    ),
    path(
        'finance/create/',
        FinancesCreateView.as_view(),
        name='finances_create',
    ),
    path(
        'receipts/',
        include(
            'hasta_la_vista_money.receipts.urls',
            namespace='receipts',
        ),
    ),
    path(
        'transactions/',
        include(
            'hasta_la_vista_money.transactions.urls',
            namespace='transactions',
        ),
    ),
    path(
        'reports/',
        include('hasta_la_vista_money.reports.urls', namespace='reports'),
    ),
    path(
        'loan/',
        include('hasta_la_vista_money.loan.urls', namespace='loan'),
    ),
    path(
        'budget/',
        include('hasta_la_vista_money.budget.urls', namespace='budget'),
    ),
    path(
        'system/',
        include('hasta_la_vista_money.system.urls', namespace='system'),
    ),
    path(
        'api/',
        include('hasta_la_vista_money.api.urls', namespace='api'),
        name='api',
    ),
    path(
        'api/schema/',
        SpectacularAPIView.as_view(schema=None),
        name='schema',
    ),
    path(
        'api/schema/swagger-ui/',
        SpectacularSwaggerView.as_view(url_name='schema', schema=None),
        name='swagger-ui',
    ),
    path('admin/', admin.site.urls),
    path('__debug__/', include('debug_toolbar.urls')),
]

if settings.DEBUG:
    urlpatterns += [
        path('__reload__/', include('django_browser_reload.urls')),
    ]

if settings.DEBUG or settings.IS_TESTING:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', debug_media_serve),
        re_path(r'^static/(?P<path>.*)$', debug_static_serve),
    ]
