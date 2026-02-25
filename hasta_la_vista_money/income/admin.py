from django.contrib import admin

from hasta_la_vista_money.income.models import Income, IncomeCategory


@admin.register(Income)
class IncomeAdmin(admin.ModelAdmin):
    list_display = ('date', 'amount', 'category', 'account', 'user')
    list_select_related = ('user', 'account', 'category')
    list_filter = ('date', 'category__name')
    search_fields = ('user__username', 'category__name')
    date_hierarchy = 'date'


@admin.register(IncomeCategory)
class IncomeCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'parent_category')
    list_select_related = ('user', 'parent_category')
    search_fields = ('name', 'user__username')
