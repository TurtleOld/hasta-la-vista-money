from django.contrib import admin

from hasta_la_vista_money.receipts.models import Product, Receipt, Seller


@admin.register(Seller)
class SellerAdmin(admin.ModelAdmin):
    list_display = ('name_seller', 'retail_place', 'user')
    list_select_related = ('user',)
    search_fields = ('name_seller', 'user__username')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('product_name', 'price', 'quantity', 'amount', 'user')
    list_select_related = ('user',)
    search_fields = ('product_name', 'user__username')


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('receipt_date', 'total_sum', 'seller', 'account', 'user')
    list_select_related = ('user', 'account', 'seller')
    list_filter = ('receipt_date', 'operation_type')
    search_fields = ('user__username', 'seller__name_seller')
    date_hierarchy = 'receipt_date'
