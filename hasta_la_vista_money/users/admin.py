from django.contrib import admin

from hasta_la_vista_money.users.models import TokenAdmin, User

admin.site.register(User, TokenAdmin)
