from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from hasta_la_vista_money.users.views import (
    IndexView,
    LoginUser,
    LogoutUser,
)

urlpatterns = [
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
    path(
        'receipts/',
        include(
            'hasta_la_vista_money.receipts.urls',
            namespace='receipts',
        ),
    ),
    path(
        'income/',
        include(
            'hasta_la_vista_money.income.urls',
            namespace='income',
        ),
    ),
    path(
        'expense/',
        include(
            'hasta_la_vista_money.expense.urls',
            namespace='expense',
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
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
