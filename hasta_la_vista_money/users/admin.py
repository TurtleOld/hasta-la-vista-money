from django.contrib import admin

from hasta_la_vista_money.users.models import (
    FamilyGroupMembership,
    FamilyInvite,
    TokenAdmin,
    User,
)

admin.site.register(User, TokenAdmin)
admin.site.register(FamilyGroupMembership)
admin.site.register(FamilyInvite)
