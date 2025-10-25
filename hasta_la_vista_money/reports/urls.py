from django.urls import path

from hasta_la_vista_money.reports.views import ReportView

app_name = 'reports'
urlpatterns = [
    path('', ReportView.as_view(), name='list'),
]
