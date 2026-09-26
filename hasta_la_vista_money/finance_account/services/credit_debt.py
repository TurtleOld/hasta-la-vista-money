"""Credit-card debt derived from the account balance.

The debt of a credit card is the credit limit minus the current account
balance. Movements reconstructed from history are only used for
period-scoped calculations, never for the total debt.
"""

from decimal import Decimal

from django.db.models import QuerySet

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account


def card_debt_for_balance(account: Account, balance: Decimal) -> Decimal:
    """Return credit-card debt for the given account balance.

    Args:
        account: Credit account with a credit limit.
        balance: Account balance to derive the debt from.

    Returns:
        Non-negative debt equal to ``limit - balance``.
    """
    limit = Decimal(account.limit_credit or 0)
    return max(limit - balance, Decimal(0))


def compute_total_credit_debt(accounts: QuerySet[Account]) -> Decimal:
    """Sum balance-derived debt across the credit accounts in a queryset.

    Args:
        accounts: Accounts to inspect; non-credit accounts are ignored.

    Returns:
        Non-negative Decimal representing total credit-card debt.
    """
    credit_accounts = accounts.filter(
        type_account__in=constants.CREDIT_ACCOUNT_TYPES,
    )
    return sum(
        (
            card_debt_for_balance(account, Decimal(account.balance))
            for account in credit_accounts
        ),
        Decimal(0),
    )
