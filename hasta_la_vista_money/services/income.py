from datetime import date, datetime, time
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


@transaction.atomic
def add_income(
    user: User,
    account: Account,
    category: IncomeCategory,
    amount: Decimal,
    date: date,
) -> Income:
    """
    Create a new income record and update the account balance.
    """
    if account.user != user:
        raise PermissionDenied(
            _('You do not have permission to add income to this account.'),
        )
    account.balance += amount
    account.save()
    date_value = date
    if isinstance(date_value, date) and not isinstance(date_value, datetime):
        date_value = timezone.make_aware(datetime.combine(date_value, time.min))
    elif isinstance(date_value, datetime) and timezone.is_naive(date_value):
        date_value = timezone.make_aware(date_value)
    return Income.objects.create(
        user=user,
        account=account,
        category=category,
        amount=amount,
        date=date_value,
    )


@transaction.atomic
def update_income(
    user: User,
    income: Income,
    account: Account,
    category: IncomeCategory,
    amount: Decimal,
    date: date,
) -> Income:
    """
    Update an existing income record and adjust account balances.
    """
    if income.user != user or account.user != user:
        raise PermissionDenied(
            _('You do not have permission to update this income.'),
        )
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
    date_value = date
    if isinstance(date_value, date) and not isinstance(date_value, datetime):
        date_value = timezone.make_aware(datetime.combine(date_value, time.min))
    elif isinstance(date_value, datetime) and timezone.is_naive(date_value):
        date_value = timezone.make_aware(date_value)
    income.date = date_value
    income.save()
    return income


@transaction.atomic
def delete_income(user: User, income: Income) -> None:
    """
    Delete an income record and update the account balance.
    """
    if income.user != user:
        raise PermissionDenied(
            _('You do not have permission to delete this income.'),
        )
    account = income.account
    account.balance -= income.amount
    account.save()
    income.delete()


@transaction.atomic
def copy_income(user: User, income_id: int) -> Income:
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
    new_income.account.balance += new_income.amount
    new_income.account.save()
    return new_income
