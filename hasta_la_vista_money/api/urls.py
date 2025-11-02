from django.urls import include, path

app_name = 'api'
urlpatterns = [
    path(
        'auth/',
        include(
            'hasta_la_vista_money.authentication.urls',
            namespace='authentication',
        ),
    ),
    path(
        'finaccount/',
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
        'budget/',
        include(
            'hasta_la_vista_money.budget.urls',
            namespace='budget',
        ),
    ),
]
