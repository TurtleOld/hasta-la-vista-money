"""Bank-specific calculators for credit card grace periods."""

from calendar import monthrange
from datetime import datetime, time
from typing import TYPE_CHECKING

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.constants import RECEIPT_OPERATION_PURCHASE
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services.bank_constants import (
    BANK_RAIFFEISENBANK,
    BANK_SBERBANK,
)
from hasta_la_vista_money.finance_account.services.protocols import (
    BankCalculatorProtocol,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.repositories import ExpenseRepository
    from hasta_la_vista_money.receipts.repositories import ReceiptRepository


class SberbankCalculator:
    """Calculator for Sberbank credit card grace periods."""

    def calculate_grace_period(
        self,
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate grace period for Sberbank credit card.

        Args:
            account: Account to calculate grace period for.
            purchase_start: Start of purchase period.
            purchase_end: End of purchase period.

        Returns:
            Tuple of (grace_end, payments_start, payments_end) datetimes.
        """
        grace_end_date = purchase_start + relativedelta(
            months=constants.GRACE_PERIOD_MONTHS_SBERBANK,
        )
        last_day_grace = monthrange(
            grace_end_date.year,
            grace_end_date.month,
        )[1]
        grace_end = timezone.make_aware(
            datetime.combine(
                grace_end_date.replace(day=last_day_grace),
                time.max,
            ),
        )
        payments_start = purchase_end + relativedelta(
            seconds=constants.ONE_SECOND,
        )
        payments_end = grace_end

        return grace_end, payments_start, payments_end


class RaiffeisenbankCalculator:
    """Calculator for Raiffeisenbank credit card grace periods."""

    def __init__(
        self,
        expense_repository: 'ExpenseRepository',
        receipt_repository: 'ReceiptRepository',
    ) -> None:
        """Initialize RaiffeisenbankCalculator.

        Args:
            expense_repository: Repository for expense data access.
            receipt_repository: Repository for receipt data access.
        """
        self.expense_repository = expense_repository
        self.receipt_repository = receipt_repository

    def _get_first_purchase_in_month(
        self,
        account: Account,
        month_start: datetime,
    ) -> datetime | None:
        """Find first purchase date in month for credit card.

        Args:
            account: Account to search purchases for.
            month_start: Start datetime of the month.

        Returns:
            Datetime of first purchase if found, None otherwise.
        """
        month_end = timezone.make_aware(
            datetime.combine(
                month_start.replace(
                    day=monthrange(month_start.year, month_start.month)[1],
                ),
                time.max,
            ),
        )

        first_expense = (
            self.expense_repository.filter(
                account=account,
                date__range=(month_start, month_end),
            )
            .order_by('date')
            .first()
        )

        first_receipt = (
            self.receipt_repository.filter(
                account=account,
                operation_type=RECEIPT_OPERATION_PURCHASE,
                receipt_date__range=(month_start, month_end),
            )
            .order_by('receipt_date')
            .first()
        )
        if first_expense and first_receipt:
            return min(first_expense.date, first_receipt.receipt_date)
        if first_expense:
            return first_expense.date
        if first_receipt:
            return first_receipt.receipt_date
        return None

    def calculate_grace_period(
        self,
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate grace period for Raiffeisenbank credit card.

        Args:
            account: Account to calculate grace period for.
            purchase_start: Start of purchase period.
            purchase_end: End of purchase period.

        Returns:
            Tuple of (grace_end, payments_start, payments_end) datetimes.
        """
        first_purchase = self._get_first_purchase_in_month(
            account,
            purchase_start,
        )

        if first_purchase:
            if timezone.is_naive(first_purchase):
                first_purchase = timezone.make_aware(first_purchase)

            grace_end = first_purchase + relativedelta(
                days=constants.GRACE_PERIOD_DAYS_RAIFFEISENBANK,
            )
            grace_end = timezone.make_aware(
                datetime.combine(grace_end.date(), time.max),
            )
        else:
            grace_end = purchase_end

        payments_start = purchase_end + relativedelta(
            seconds=constants.ONE_SECOND,
        )
        payments_end = grace_end

        return grace_end, payments_start, payments_end


class DefaultBankCalculator:
    """Default calculator for banks without specific logic."""

    def calculate_grace_period(
        self,
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate default grace period.

        Args:
            account: Account to calculate grace period for.
            purchase_start: Start of purchase period.
            purchase_end: End of purchase period.

        Returns:
            Tuple of (grace_end, payments_start, payments_end) datetimes.
        """
        grace_end = purchase_end
        payments_start = purchase_end + relativedelta(
            seconds=constants.ONE_SECOND,
        )
        payments_end = grace_end
        return grace_end, payments_start, payments_end


def create_bank_calculator(
    bank: str,
    expense_repository: 'ExpenseRepository | None' = None,
    receipt_repository: 'ReceiptRepository | None' = None,
) -> BankCalculatorProtocol:
    """Create bank calculator based on bank type.

    Args:
        bank: Bank identifier.
        expense_repository: Repository for expense data access (required
            for Raiffeisenbank).
        receipt_repository: Repository for receipt data access (required
            for Raiffeisenbank).

    Returns:
        Bank calculator instance.

    Raises:
        ValueError: If required repositories are not provided for
            Raiffeisenbank.
    """
    if bank == BANK_SBERBANK:
        return SberbankCalculator()
    if bank == BANK_RAIFFEISENBANK:
        if expense_repository is None or receipt_repository is None:
            raise ValueError(
                'Expense and receipt repositories are required for '
                'Raiffeisenbank calculator',
            )
        return RaiffeisenbankCalculator(
            expense_repository=expense_repository,
            receipt_repository=receipt_repository,
        )
    return DefaultBankCalculator()
