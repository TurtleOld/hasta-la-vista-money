"""Admin configuration for finance account models."""

from django.contrib import admin

from hasta_la_vista_money.finance_account.models import (
    Account,
    Bank,
    TransferMoneyLog,
)


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin[Bank]):
    list_display = ('code', 'name', 'is_system', 'user', 'created_at')
    list_filter = ('is_system',)
    search_fields = ('code', 'name')
    ordering = ('name',)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin[Account]):
    list_display = (
        'name_account',
        'type_account',
        'balance',
        'currency',
        'user',
    )
    list_select_related = ('user',)
    list_filter = ('type_account', 'currency')
    search_fields = ('name_account', 'user__username')


@admin.register(TransferMoneyLog)
class TransferMoneyLogAdmin(admin.ModelAdmin[TransferMoneyLog]):
    list_display = (
        'exchange_date',
        'amount',
        'from_account',
        'to_account',
        'user',
    )
    list_select_related = ('user', 'from_account', 'to_account')
    search_fields = ('user__username',)
    date_hierarchy = 'exchange_date'
