from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from hasta_la_vista_money.users.views import IndexView, LoginUser, LogoutUser

urlpatterns = [
    re_path(
        'users/',
        include(
            'hasta_la_vista_money.users.urls',
            namespace='users',
        ),
        name='list',
    ),
    path('', IndexView.as_view(), name='index'),
    path(
        'login/',
        LoginUser.as_view(
            redirect_authenticated_user=True,
        ),
        name='login',
    ),
    path(
        'logout/',
        LogoutUser.as_view(),
        {'next_page': settings.LOGOUT_REDIRECT_URL},
        name='logout',
    ),
    path(
        'hasta-la-vista-money/',
        include(
            'hasta_la_vista_money.finance_account.urls',
            namespace='applications',
        ),
        name='applications',
    ),
    path(
        'receipts/',
        include(
            'hasta_la_vista_money.receipts.urls',
            namespace='receipts',
        ),
        name='receipt',
    ),
    path(
        'income/',
        include(
            'hasta_la_vista_money.income.urls',
            namespace='income',
        ),
        name='income',
    ),
    path(
        'expense/',
        include(
            'hasta_la_vista_money.expense.urls',
            namespace='expense',
        ),
        name='expense',
    ),
    path(
        'finance_account/',
        include(
            'hasta_la_vista_money.finance_account.urls',
            namespace='finance_account',
        ),
        name='finance_account',
    ),
    path(
        'reports/',
        include('hasta_la_vista_money.reports.urls', namespace='reports'),
        name='reports',
    ),
    path(
        'loan/',
        include('hasta_la_vista_money.loan.urls', namespace='loan'),
        name='loan',
    ),
    path(
        'budget/',
        include('hasta_la_vista_money.budget.urls', namespace='budget'),
        name='budget',
    ),
]

if 'rosetta' in settings.INSTALLED_APPS:
    urlpatterns += [re_path(r'^rosetta/', include('rosetta.urls'))]
if settings.DEBUG:
    urlpatterns += (path('__debug__/', include('debug_toolbar.urls')),)
    urlpatterns += (path('adminushka/', admin.site.urls),)
