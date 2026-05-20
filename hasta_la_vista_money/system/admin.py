from django.contrib import admin

from hasta_la_vista_money.system.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'model_name', 'object_pk', 'action')
    list_filter = ('action', 'model_name', 'created_at')
    list_select_related = ('user',)
    readonly_fields = (
        'user',
        'model_name',
        'object_pk',
        'action',
        'diff',
        'created_at',
    )
    search_fields = ('user__username', 'model_name', 'object_pk')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request) -> bool:
        del request
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        del request, obj
        return False
