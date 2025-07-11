from typing import Optional
from django.contrib.auth.models import Group
from django.db.models import Sum, QuerySet
from hasta_la_vista_money.finance_account.models import Account, TransferMoneyLog
from hasta_la_vista_money.users.models import User


def get_accounts_for_user_or_group(user: User, group_id: Optional[str]) -> QuerySet[Account]:
    """
    Returns accounts for a user or for all users in a group if group_id is provided.
    """
    if group_id and group_id != 'my':
        try:
            group = Group.objects.get(pk=group_id)
            users_in_group = group.user_set.all()
            return Account.objects.filter(user__in=users_in_group).select_related('user')
        except Group.DoesNotExist:
            return Account.objects.none()
    return Account.objects.filter(user=user).select_related('user')


def get_sum_all_accounts(accounts: QuerySet[Account]) -> float:
    """
    Returns the sum of balances for the given accounts queryset.
    """
    return accounts.aggregate(total=Sum('balance'))['total'] or 0


def get_transfer_money_log(user: User, limit: int = 10) -> QuerySet[TransferMoneyLog]:
    """
    Returns the latest transfer money logs for the user.
    """
    return (
        TransferMoneyLog.objects.filter(user=user)
        .select_related('to_account', 'from_account')
        .order_by('-created_at')[:limit]
    ) 