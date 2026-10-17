"""Balance trend: daily summed balances of one currency's accounts."""

from datetime import timedelta
from decimal import Decimal
from typing import TypedDict

from django.db.models import QuerySet
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services.balance_history_service import (  # noqa: E501
    BalanceHistoryService,
)


class BalanceTrendPoint(TypedDict):
    """Type definition for a balance trend data point."""

    date: str
    balance: float


class BalanceTrendData(TypedDict):
    """Type definition for balance trend response."""

    current_balance: float
    delta_absolute: float
    delta_percent: float
    series: list[BalanceTrendPoint]
    has_data: bool


class BalanceTrendService:
    """Sums `BalanceHistoryService` balances of one currency's accounts."""

    # Period definitions in days
    PERIODS = {
        '7d': 7,
        '30d': 30,
        '12m': 365,
    }

    def __init__(self, balance_history_service: BalanceHistoryService) -> None:
        self.balance_history_service = balance_history_service

    def get_balance_trend(
        self,
        accounts: QuerySet[Account],
        currency: str,
        period: str = '30d',
    ) -> BalanceTrendData:
        """Compute the balance trend of `accounts` in `currency`.

        Args:
            accounts: Accounts to include; other currencies are skipped.
            currency: Currency code of the trend.
            period: Period string ('7d', '30d', '12m').

        Returns:
            BalanceTrendData with current balance, delta, and series.
        """
        selected = list(accounts.filter(currency=currency))
        if not selected:
            return {
                'current_balance': 0.0,
                'delta_absolute': 0.0,
                'delta_percent': 0.0,
                'series': [],
                'has_data': False,
            }

        current_balance = sum(
            (account.balance for account in selected),
            Decimal(0),
        )
        today = timezone.localdate()
        balances = self.balance_history_service.daily_balances(
            selected,
            today - timedelta(days=self.PERIODS.get(period, 30)),
            today,
        )
        start_balance = next(iter(balances.values()))
        delta_absolute = current_balance - start_balance
        delta_percent = (
            delta_absolute / start_balance * 100
            if start_balance
            else Decimal(0)
        )

        return {
            'current_balance': float(current_balance),
            'delta_absolute': float(round(delta_absolute, 2)),
            'delta_percent': float(round(delta_percent, 2)),
            'series': [
                {'date': day.isoformat(), 'balance': float(balance)}
                for day, balance in balances.items()
            ],
            'has_data': True,
        }
