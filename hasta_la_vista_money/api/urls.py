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
        'users/',
        include('hasta_la_vista_money.users.api_urls', namespace='users'),
    ),
    path(
        'expense/',
        include('hasta_la_vista_money.expense.api_urls', namespace='expense'),
    ),
    path(
        'income/',
        include('hasta_la_vista_money.income.api_urls', namespace='income'),
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
