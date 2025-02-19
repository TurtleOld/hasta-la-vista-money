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
        'finance-account/',
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
]
