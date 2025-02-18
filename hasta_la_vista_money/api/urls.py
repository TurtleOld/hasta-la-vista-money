from django.urls import path, include

app_name = 'api'
urlpatterns = [
    path(
        'auth',
        include(
            'hasta_la_vista_money.authentication.urls',
            'authentication',
        ),
    )
]
