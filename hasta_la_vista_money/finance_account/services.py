from typing import Optional, Any, Dict
from django.contrib.auth.models import Group
from django.db.models import Sum, QuerySet
from hasta_la_vista_money.finance_account.models import Account, TransferMoneyLog
from hasta_la_vista_money.users.models import User
from decimal import Decimal
from datetime import date, datetime, time
from dateutil.relativedelta import relativedelta
from calendar import monthrange
from django.utils import timezone
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt


def get_accounts_for_user_or_group(
    user: User, group_id: Optional[str]
) -> QuerySet[Account]:
    """
    Returns accounts for a user or for all users in a group if group_id is provided.
    """
    if group_id and group_id != 'my':
        try:
            group = Group.objects.get(pk=group_id)
            users_in_group = group.user_set.all()
            return Account.objects.filter(user__in=users_in_group).select_related(
                'user'
            )
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


def transfer_money_service(
    from_account: Account,
    to_account: Account,
    amount: Decimal,
) -> bool:
    """
    Transfers a specified amount from one account to another.
    Returns True if the transfer was successful, False otherwise (e.g., insufficient funds).

    Args:
        from_account (Account): The account to transfer money from.
        to_account (Account): The account to transfer money to.
        amount (Decimal): The amount to transfer.

    Returns:
        bool: True if transfer succeeded, False otherwise.
    """
    if amount <= from_account.balance:
        from_account.balance -= amount
        to_account.balance += amount
        from_account.save()
        to_account.save()
        return True
    return False


def get_credit_card_debt_service(
    account: Account,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
) -> Decimal:
    """
    Calculates the credit card (or credit account) debt for a given period.
    If no period is specified, calculates the current debt.
    Considers expenses, incomes, and receipts (purchases and returns).

    Args:
        account (Account): The account to calculate debt for.
        start_date (date|datetime|None): Start of the period (inclusive).
        end_date (date|datetime|None): End of the period (inclusive).

    Returns:
        Decimal: The calculated debt.
    """
    expense_qs = Expense.objects.filter(account=account)
    income_qs = Income.objects.filter(account=account)
    receipt_qs = Receipt.objects.filter(account=account)

    if start_date and end_date:
        if isinstance(start_date, date) and not isinstance(start_date, datetime):
            start_dt = datetime.combine(start_date, time.min)
        else:
            start_dt = start_date
        if isinstance(end_date, date) and not isinstance(end_date, datetime):
            end_dt = datetime.combine(end_date, time.max)
        else:
            end_dt = end_date
        expense_qs = expense_qs.filter(date__range=(start_dt, end_dt))
        income_qs = income_qs.filter(date__range=(start_dt, end_dt))
        receipt_qs = receipt_qs.filter(receipt_date__range=(start_dt, end_dt))

    total_expense = expense_qs.aggregate(total=Sum('amount'))['total'] or 0
    total_income = income_qs.aggregate(total=Sum('amount'))['total'] or 0
    total_receipt_expense = (
        receipt_qs.filter(operation_type=1).aggregate(total=Sum('total_sum'))['total']
        or 0
    )
    total_receipt_return = (
        receipt_qs.filter(operation_type=2).aggregate(total=Sum('total_sum'))['total']
        or 0
    )

    debt = (total_expense + total_receipt_expense) - (
        total_income + total_receipt_return
    )
    return debt


def calculate_grace_period_info_service(
    account: Account,
    purchase_month: Any,
) -> Dict[str, Any]:
    """
    Calculates grace period information for a credit card.
    Logic: 1 month for purchases + 3 months for repayment.
    Example: purchases in May -> repayment due by end of August.

    Args:
        account (Account): The credit account.
        purchase_month (date|datetime): The month of purchases (first day of month).

    Returns:
        dict: Information about the grace period, including dates, debts, and overdue status.
    """
    # Начало месяца покупок
    purchase_start = purchase_month.replace(day=1)

    # Конец месяца покупок (23:59:59)
    last_day = monthrange(purchase_start.year, purchase_start.month)[1]
    purchase_end = datetime.combine(purchase_start.replace(day=last_day), time.max)

    # Конец беспроцентного периода (3 месяца после месяца покупок, 23:59:59)
    grace_end_date = purchase_start + relativedelta(months=3)
    last_day_grace = monthrange(grace_end_date.year, grace_end_date.month)[1]
    grace_end = datetime.combine(
        grace_end_date.replace(day=last_day_grace),
        time.max,
    )

    # Рассчитываем долг за месяц покупок
    debt_for_month = get_credit_card_debt_service(account, purchase_start, purchase_end)

    # Рассчитываем платежи за период погашения
    payments_start = purchase_end + relativedelta(seconds=1)
    payments_end = grace_end
    payments_for_period = get_credit_card_debt_service(
        account, payments_start, payments_end
    )

    # Итоговый долг после беспроцентного периода
    final_debt = (debt_for_month or 0) + (payments_for_period or 0)

    return {
        'purchase_month': purchase_start.strftime('%m.%Y'),
        'purchase_start': purchase_start,
        'purchase_end': purchase_end,
        'grace_end': grace_end,
        'debt_for_month': debt_for_month,
        'payments_for_period': payments_for_period,
        'final_debt': final_debt,
        'is_overdue': timezone.now() > grace_end and final_debt > 0,
        'days_until_due': (
            (grace_end.date() - timezone.now().date()).days
            if timezone.now() <= grace_end
            else 0
        ),
    }
