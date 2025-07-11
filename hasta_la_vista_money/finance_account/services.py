"""
Services for finance account operations.

This module contains business logic for account operations,
separating it from form and view logic.
"""

from calendar import monthrange
from datetime import datetime, time
from decimal import Decimal
from typing import Any, Dict, Optional

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import Account, TransferMoneyLog
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_different_accounts,
    validate_positive_amount,
)
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


class TransferService:
    """Service for handling money transfers between accounts."""

    @staticmethod
    @transaction.atomic
    def transfer_money(
        from_account: Account,
        to_account: Account,
        amount: Decimal,
        user: User,
        exchange_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> TransferMoneyLog:
        """
        Transfer money between accounts with validation and logging.

        Args:
            from_account: Source account
            to_account: Destination account
            amount: Transfer amount
            user: User performing the transfer
            exchange_date: Transfer date (optional)
            notes: Transfer notes (optional)

        Returns:
            TransferMoneyLog: Created transfer log entry

        Raises:
            ValueError: If transfer fails
        """
        validate_positive_amount(amount)
        validate_different_accounts(from_account, to_account)
        validate_account_balance(from_account, amount)

        if from_account.transfer_money(to_account, amount):
            transfer_log = TransferMoneyLog.objects.create(
                user=user,
                from_account=from_account,
                to_account=to_account,
                amount=amount,
                exchange_date=exchange_date,
                notes=notes or '',
            )
            return transfer_log

        raise ValueError('Transfer failed - insufficient funds or invalid accounts')


class AccountService:
    """Service for account-related operations."""

    @staticmethod
    def get_user_accounts(user: User) -> list[Account]:
        """
        Get all accounts for a specific user.

        Args:
            user: User whose accounts to retrieve

        Returns:
            List of user's accounts
        """
        return list(Account.objects.filter(user=user).select_related('user'))

    @staticmethod
    def get_account_by_id(account_id: int, user: User) -> Optional[Account]:
        """
        Get a specific account by ID for a user.

        Args:
            account_id: Account ID
            user: User who owns the account

        Returns:
            Account instance or None if not found
        """
        try:
            return Account.objects.get(id=account_id, user=user)
        except Account.DoesNotExist:
            return None

    @staticmethod
    def get_credit_card_debt(
        account: Account,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
    ) -> Optional[Decimal]:
        """
        Calculates the credit card (or credit account) debt for a given period.
        If no period is specified, calculates the current debt.
        Considers expenses, incomes, and receipts (purchases and returns).

        Args:
            account: The account to calculate debt for
            start_date: Start of the period (inclusive)
            end_date: End of the period (inclusive)

        Returns:
            Optional[Decimal]: The calculated debt, or None if not a credit account
        """
        if account.type_account not in ('CreditCard', 'Credit'):
            return None

        expense_qs = Expense.objects.filter(account=account)
        income_qs = Income.objects.filter(account=account)
        receipt_qs = Receipt.objects.filter(account=account)

        if start_date and end_date:
            expense_qs = expense_qs.filter(date__range=(start_date, end_date))
            income_qs = income_qs.filter(date__range=(start_date, end_date))
            receipt_qs = receipt_qs.filter(receipt_date__range=(start_date, end_date))

        total_expense = expense_qs.aggregate(total=Sum('amount'))['total'] or 0
        total_income = income_qs.aggregate(total=Sum('amount'))['total'] or 0
        total_receipt_expense = (
            receipt_qs.filter(operation_type=1).aggregate(total=Sum('total_sum'))[
                'total'
            ]
            or 0
        )
        total_receipt_return = (
            receipt_qs.filter(operation_type=2).aggregate(total=Sum('total_sum'))[
                'total'
            ]
            or 0
        )

        debt = (total_expense + total_receipt_expense) - (
            total_income + total_receipt_return
        )
        return debt

    @staticmethod
    def calculate_grace_period_info(
        account: Account, purchase_month: Any
    ) -> Dict[str, Any]:
        """
        Calculates grace period information for a credit card.
        Logic: 1 month for purchases + 3 months for repayment.
        Example: purchases in May -> repayment due by end of August.

        Args:
            account: The credit account
            purchase_month: The month of purchases (first day of month)

        Returns:
            dict: Information about the grace period, including dates, debts, and overdue status
        """
        if account.type_account not in ('CreditCard', 'Credit'):
            return {}

        purchase_start = purchase_month.replace(day=1)

        last_day = monthrange(purchase_start.year, purchase_start.month)[1]
        purchase_end = datetime.combine(purchase_start.replace(day=last_day), time.max)

        grace_end_date = purchase_start + relativedelta(months=3)
        last_day_grace = monthrange(grace_end_date.year, grace_end_date.month)[1]
        grace_end = datetime.combine(
            grace_end_date.replace(day=last_day_grace),
            time.max,
        )

        debt_for_month = AccountService.get_credit_card_debt(
            account, purchase_start, purchase_end
        )

        payments_start = purchase_end + relativedelta(seconds=1)
        payments_end = grace_end
        payments_for_period = AccountService.get_credit_card_debt(
            account, payments_start, payments_end
        )

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


def get_accounts_for_user_or_group(user, group_id=None):
    if not group_id or group_id == 'my':
        return Account.objects.filter(user=user)
    else:
        users_in_group = User.objects.filter(groups__id=group_id)
        return Account.objects.filter(user__in=users_in_group)


def get_sum_all_accounts(accounts):
    """Calculate total balance for a queryset of accounts."""
    return sum(acc.balance for acc in accounts)


def get_transfer_money_log(user, limit=10):
    """Get recent transfer logs for a user."""
    from hasta_la_vista_money.finance_account.models import TransferMoneyLog

    return TransferMoneyLog.objects.filter(user=user).order_by('-exchange_date')[:limit]
