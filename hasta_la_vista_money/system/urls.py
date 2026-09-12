"""URL configuration for system views."""

from django.urls import path

from hasta_la_vista_money.system.views import AuditLogView, AuditOperationView

app_name = 'system'

urlpatterns = [
    path('audit/', AuditLogView.as_view(), name='auditlog'),
    path(
        'audit/<str:operation_key>/',
        AuditOperationView.as_view(),
        name='auditlog_operation',
    ),
]
