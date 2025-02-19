from django.urls import include, path

app_name = 'api'
urlpatterns = [
    path(
        'auth/',
        include(
            'hasta_la_vista_money.authentication.urls',
            'authentication',
        ),
    ),
    path(
        'finacc/',
        include(
            'hasta_la_vista_money.finance_account.urls',
            namespace='finance_account',
        ),
    ),
]
