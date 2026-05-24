"""Django admin registration for transactions and categories."""

from django.contrib import admin

from hasta_la_vista_money.transactions.models import Category, Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Admin view for the unified Transaction model."""

    list_display = ('date', 'type', 'amount', 'category', 'account', 'user')
    list_select_related = ('user', 'account', 'category')
    list_filter = ('type', 'date', 'category__name')
    search_fields = ('user__username', 'category__name')
    date_hierarchy = 'date'


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin view for the unified Category model."""

    list_display = ('name', 'type', 'user', 'parent_category')
    list_select_related = ('user', 'parent_category')
    list_filter = ('type',)
    search_fields = ('name', 'user__username')
