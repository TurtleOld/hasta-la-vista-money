from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money.income.models import Income


def add_income(user, account, category, amount, date):
    """
    Create a new income record and update the account balance.
    """
    if account.user != user:
        raise PermissionDenied(
            _('You do not have permission to add income to this account.'),
        )
    account.balance += amount
    account.save()
    income = Income.objects.create(
        user=user,
        account=account,
        category=category,
        amount=amount,
        date=date,
    )
    return income


def update_income(user, income, account, category, amount, date):
    """
    Update an existing income record and adjust account balances.
    """
    if income.user != user or account.user != user:
        raise PermissionDenied(_('You do not have permission to update this income.'))
    old_account = income.account
    old_amount = income.amount
    if old_account == account:
        account.balance -= old_amount
        account.balance += amount
        account.save()
    else:
        old_account.balance -= old_amount
        old_account.save()
        account.balance += amount
        account.save()
    income.account = account
    income.category = category
    income.amount = amount
    income.date = date
    income.save()
    return income


def delete_income(user, income):
    """
    Delete an income record and update the account balance.
    """
    if income.user != user:
        raise PermissionDenied(_('You do not have permission to delete this income.'))
    account = income.account
    account.balance -= income.amount
    account.save()
    income.delete()


def copy_income(user, income_id):
    """
    Copy an income record and update the account balance for the new record.
    """
    income = get_object_or_404(Income, pk=income_id, user=user)
    new_income = Income.objects.create(
        user=income.user,
        account=income.account,
        category=income.category,
        amount=income.amount,
        date=income.date,
    )
    if new_income.account:
        new_income.account.balance += new_income.amount
        new_income.account.save()
    return new_income
