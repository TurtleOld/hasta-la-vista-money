from django.contrib import admin

from hasta_la_vista_money.receipts.models import Product, Receipt, Seller

admin.site.register(Seller)
admin.site.register(Product)
admin.site.register(Receipt)
