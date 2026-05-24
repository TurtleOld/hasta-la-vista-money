"""Service for computing balance trends from transaction history."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

from django.db.models import QuerySet, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
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
    """Service for computing balance trends from transaction history.

    Computes daily closing balances from transaction records by:
    1. Getting all transactions (income/expense) for selected accounts
    2. Sorting by date
    3. Computing running balance from earliest transaction to today
    4. Returning series for requested period with delta calculation
    """

    # Period definitions in days
    PERIODS = {
        '7d': 7,
        '30d': 30,
        '12m': 365,
    }

    def get_balance_trend(
        self,
        accounts: QuerySet[Account],
        period: str = '30d',
    ) -> BalanceTrendData:
        """Compute balance trend for given accounts over period.

        Args:
            accounts: QuerySet of Account objects to include
            period: Period string ('7d', '30d', '12m')

        Returns:
            BalanceTrendData with current balance, delta, and series
        """
        if not accounts.exists():
            return {
                'current_balance': 0.0,
                'delta_absolute': 0.0,
                'delta_percent': 0.0,
                'series': [],
                'has_data': False,
            }

        # Get current total balance
        current_balance = self._get_current_balance(accounts)

        # Get period limit
        days = self.PERIODS.get(period, 30)
        period_start = timezone.now() - timedelta(days=days)

        # Compute series from transactions
        series = self._compute_series(accounts, period_start)

        if not series:
            return {
                'current_balance': float(current_balance),
                'delta_absolute': 0.0,
                'delta_percent': 0.0,
                'series': [],
                'has_data': False,
            }

        # Get balance at period start
        period_start_balance = self._get_balance_at_date(
            accounts,
            period_start.date(),
        )

        # Calculate delta
        delta_absolute = Decimal(current_balance - period_start_balance)
        delta_percent = (
            (delta_absolute / period_start_balance * 100)
            if period_start_balance != 0
            else 0.0
        )

        return {
            'current_balance': float(current_balance),
            'delta_absolute': round(delta_absolute, 2),
            'delta_percent': round(delta_percent, 2),
            'series': series,
            'has_data': True,
        }

    def _get_current_balance(self, accounts: QuerySet[Account]) -> Decimal:
        """Get current total balance for given accounts.

        Args:
            accounts: QuerySet of Account objects

        Returns:
            Total balance as Decimal
        """
        total = accounts.aggregate(
            total=Coalesce(Sum('balance'), Decimal(0)),
        )['total']
        return total if isinstance(total, Decimal) else Decimal(str(total))

    def _compute_series(
        self,
        accounts: QuerySet[Account],
        start_date: datetime,
    ) -> list[BalanceTrendPoint]:
        """Compute daily closing balances from transactions.

        Algorithm:
        1. Get all expenses for accounts since start_date, grouped by day
        2. Get all income for accounts since start_date, grouped by day
        3. Combine into daily net changes
        4. Compute running balance starting from period start
        5. Return formatted series

        Args:
            accounts: QuerySet of Account objects
            start_date: Start date for computation

        Returns:
            List of BalanceTrendPoint dicts
        """
        account_ids = list(accounts.values_list('id', flat=True))

        daily_totals = (
            Transaction.objects.filter(
                account_id__in=account_ids,
                date__gte=start_date,
            )
            .annotate(date_only=TruncDate('date'))
            .values('date_only', 'type')
            .annotate(total=Coalesce(Sum('amount'), Decimal(0)))
            .order_by('date_only')
        )

        expenses_dict: dict[date, Decimal] = {}
        income_dict: dict[date, Decimal] = {}
        for item in daily_totals:
            target = (
                income_dict
                if item['type'] == TransactionType.INCOME
                else expenses_dict
            )
            target[item['date_only']] = item['total']

        # Get balance at period start
        starting_balance = self._get_balance_at_date(
            accounts,
            start_date.date(),
        )

        # Generate series
        series: list[BalanceTrendPoint] = []
        current_balance = starting_balance
        current_date = start_date.date()
        today = timezone.now().date()

        while current_date <= today:
            # Calculate net change for day
            day_expenses = expenses_dict.get(current_date, Decimal(0))
            day_income = income_dict.get(current_date, Decimal(0))
            current_balance = current_balance + day_income - day_expenses

            # Add to series
            series.append(
                {
                    'date': current_date.isoformat(),
                    'balance': float(current_balance),
                },
            )

            current_date += timedelta(days=1)

        return series

    def _get_balance_at_date(
        self,
        accounts: QuerySet[Account],
        target_date: date,
    ) -> Decimal:
        """Get estimated balance at a specific date.

        Computes balance by: current_balance - (expenses since date) +
        (income since date)

        Args:
            accounts: QuerySet of Account objects
            target_date: Target date for balance calculation

        Returns:
            Estimated balance as Decimal
        """
        account_ids = list(accounts.values_list('id', flat=True))
        current_balance = self._get_current_balance(accounts)

        totals_after = (
            Transaction.objects.filter(
                account_id__in=account_ids,
                date__date__gte=target_date,
            )
            .values('type')
            .annotate(total=Coalesce(Sum('amount'), Decimal(0)))
        )
        totals_by_type = {item['type']: item['total'] for item in totals_after}
        expenses_after = totals_by_type.get(TransactionType.EXPENSE, Decimal(0))
        income_after = totals_by_type.get(TransactionType.INCOME, Decimal(0))

        # Balance at target_date = current - income_after + expenses_after
        return current_balance - income_after + expenses_after
