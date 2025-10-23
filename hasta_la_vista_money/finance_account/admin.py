"""Admin configuration for finance account models.

This module registers the Account model with Django's admin interface,
enabling administrative management of financial accounts
through the Django admin.
"""

from django.contrib import admin

from hasta_la_vista_money.finance_account.models import Account

admin.site.register(Account)
