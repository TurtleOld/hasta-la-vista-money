"""Service for credit card calculation operations."""

from calendar import monthrange
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from dateutil.relativedelta import relativedelta
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT,
    ACCOUNT_TYPE_CREDIT_CARD,
    RECEIPT_OPERATION_PURCHASE,
    RECEIPT_OPERATION_RETURN,
)
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.finance_account.services.bank_calculators import (
    create_bank_calculator,
)
from hasta_la_vista_money.finance_account.services.bank_constants import (
    BANK_RAIFFEISENBANK,
    SUPPORTED_BANKS,
)
from hasta_la_vista_money.finance_account.services.types import (
    GracePeriodInfoDict,
    PaymentScheduleStatementDict,
    RaiffeisenbankScheduleDict,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.repositories import ExpenseRepository
    from hasta_la_vista_money.income.repositories import IncomeRepository
    from hasta_la_vista_money.receipts.repositories import ReceiptRepository


class CreditCalculationService:
    """Service for credit card debt and grace period calculations.

    Handles calculations for credit card debt, grace periods,
    and payment schedules for different banks.
    """

    def __init__(
        self,
        expense_repository: 'ExpenseRepository',
        income_repository: 'IncomeRepository',
        receipt_repository: 'ReceiptRepository',
    ) -> None:
        """Initialize CreditCalculationService.

        Args:
            expense_repository: Repository for expense data access.
            income_repository: Repository for income data access.
            receipt_repository: Repository for receipt data access.
        """
        self.expense_repository = expense_repository
        self.income_repository = income_repository
        self.receipt_repository = receipt_repository

    def get_credit_card_debt(
        self,
        account: Account,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> Decimal | None:
        """Calculate credit card debt for a given period.

        Calculates the debt by summing expenses and receipts (purchases)
        and subtracting income and returns for the specified period.
        Optimized to use single aggregation query where possible.

        Args:
            account: Account instance. Must be credit card or credit type.
            start_date: Optional start date for the period.
            end_date: Optional end date for the period.

        Returns:
            Decimal debt amount if account is credit type, None otherwise.
        """
        if account.type_account not in (
            ACCOUNT_TYPE_CREDIT_CARD,
            ACCOUNT_TYPE_CREDIT,
        ):
            return None

        start_date_dt: datetime | None = None
        end_date_dt: datetime | None = None

        if start_date and end_date:
            if isinstance(start_date, datetime):
                start_date_dt = start_date
            elif isinstance(start_date, date):
                start_date_dt = timezone.make_aware(
                    datetime.combine(start_date, time.min),
                )
            if isinstance(end_date, datetime):
                end_date_dt = end_date
            elif isinstance(end_date, date):
                end_date_dt = timezone.make_aware(
                    datetime.combine(end_date, time.max),
                )

        expenses_queryset = self.expense_repository.filter(account=account)
        income_queryset = self.income_repository.filter(account=account)
        receipts_queryset = self.receipt_repository.filter(account=account)

        if start_date_dt and end_date_dt:
            expenses_queryset = expenses_queryset.filter(
                date__range=(start_date_dt, end_date_dt),
            )
            income_queryset = income_queryset.filter(
                date__range=(start_date_dt, end_date_dt),
            )
            receipts_queryset = receipts_queryset.filter(
                receipt_date__range=(start_date_dt, end_date_dt),
            )

        total_expense = (
            expenses_queryset.aggregate(total=Sum('amount'))['total'] or 0
        )
        total_income = (
            income_queryset.aggregate(total=Sum('amount'))['total'] or 0
        )

        receipt_aggregation = receipts_queryset.aggregate(
            total_expense=Coalesce(
                Sum(
                    'total_sum',
                    filter=Q(operation_type=RECEIPT_OPERATION_PURCHASE),
                ),
                0,
                output_field=DecimalField(),
            ),
            total_return=Coalesce(
                Sum(
                    'total_sum',
                    filter=Q(operation_type=RECEIPT_OPERATION_RETURN),
                ),
                0,
                output_field=DecimalField(),
            ),
        )
        total_receipt_expense = receipt_aggregation['total_expense'] or 0
        total_receipt_return = receipt_aggregation['total_return'] or 0

        result = (total_expense + total_receipt_expense) - (
            total_income + total_receipt_return
        )
        return Decimal(str(result))

    def _find_first_purchase_in_month(
        self,
        account: Account,
        month_start: datetime,
    ) -> datetime | None:
        """Find first purchase date in month for credit card.

        Searches for the earliest expense or receipt purchase in the
        given month. Optimized to fetch only first record.

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

    def _calculate_purchase_period(
        self,
        purchase_month: date | datetime,
    ) -> tuple[datetime, datetime]:
        """Calculate purchase period start and end dates.

        Args:
            purchase_month: Month to calculate period for.

        Returns:
            Tuple of (purchase_start, purchase_end) datetimes for the month.
        """
        purchase_start = timezone.make_aware(
            datetime.combine(purchase_month.replace(day=1), time.min),
        )
        last_day_of_month = monthrange(
            purchase_start.year, purchase_start.month
        )[1]
        purchase_end = timezone.make_aware(
            datetime.combine(
                purchase_start.date().replace(day=last_day_of_month),
                time.max,
            ),
        )

        return purchase_start, purchase_end

    def _calculate_grace_period_by_bank(
        self,
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate grace period based on bank type.

        Uses bank calculator factory to get appropriate calculator.

        Args:
            account: Account to calculate grace period for.
            purchase_start: Start of purchase period.
            purchase_end: End of purchase period.

        Returns:
            Tuple of (grace_end, payments_start, payments_end) datetimes.
        """
        calculator = create_bank_calculator(
            account.bank,
            expense_repository=self.expense_repository,
            receipt_repository=self.receipt_repository,
        )
        return calculator.calculate_grace_period(
            account,
            purchase_start,
            purchase_end,
        )

    def _calculate_debt_info(
        self,
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
        payments_start: datetime,
        payments_end: datetime,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Calculate debt information for the period.

        Args:
            account: Account to calculate debt for.
            purchase_start: Start of purchase period.
            purchase_end: End of purchase period.
            payments_start: Start of payments period.
            payments_end: End of payments period.

        Returns:
            Tuple of (purchase_period_debt, payment_period_debt, total_debt).
        """
        purchase_period_debt = self.get_credit_card_debt(
            account,
            purchase_start,
            purchase_end,
        )

        if account.bank in SUPPORTED_BANKS:
            payment_period_debt = self.get_credit_card_debt(
                account,
                payments_start,
                payments_end,
            )
        else:
            payment_period_debt = Decimal(str(constants.ZERO))

        total_debt = (purchase_period_debt or constants.ZERO) + (
            payment_period_debt or constants.ZERO
        )

        return (  # type: ignore[return-value]
            purchase_period_debt or constants.ZERO,
            payment_period_debt or constants.ZERO,
            total_debt,
        )

    def _ensure_timezone_aware(self, dt: datetime) -> datetime:
        """Ensure datetime is timezone aware.

        Args:
            dt: Datetime to check and convert.

        Returns:
            Timezone-aware datetime.
        """
        if hasattr(dt, 'utcoffset') and timezone.is_naive(dt):
            return timezone.make_aware(dt)
        return dt

    def calculate_grace_period_info(
        self,
        account: Account,
        purchase_month: date | datetime,
    ) -> GracePeriodInfoDict:
        """Calculate grace period information for a credit card.

        Args:
            account: Credit card account.
            purchase_month: Month to calculate grace period for.

        Returns:
            Dictionary with grace period information. Empty dict if account
            is not a credit card.
        """
        if account.type_account not in (
            ACCOUNT_TYPE_CREDIT_CARD,
            ACCOUNT_TYPE_CREDIT,
        ):
            return {}

        purchase_start, purchase_end = self._calculate_purchase_period(
            purchase_month,
        )

        grace_end, payments_start, payments_end = (
            self._calculate_grace_period_by_bank(
                account,
                purchase_start,
                purchase_end,
            )
        )

        purchase_period_debt, payment_period_debt, total_debt = (
            self._calculate_debt_info(
                account,
                purchase_start,
                purchase_end,
                payments_start,
                payments_end,
            )
        )

        grace_end = self._ensure_timezone_aware(grace_end)

        return {
            'purchase_month': purchase_start.strftime('%m.%Y'),
            'purchase_start': purchase_start,
            'purchase_end': purchase_end,
            'grace_end': grace_end,
            'debt_for_month': purchase_period_debt,
            'payments_for_period': payment_period_debt,
            'final_debt': total_debt,
            'is_overdue': (
                timezone.now() > grace_end and total_debt > constants.ZERO
            ),
            'days_until_due': (
                (grace_end.date() - timezone.now().date()).days
                if timezone.now() <= grace_end
                else constants.ZERO
            ),
        }

    def _validate_raiffeisenbank_account(
        self,
        account: Account,
    ) -> bool:
        """Validate if account is eligible for Raiffeisenbank payment schedule.

        Args:
            account: Account to validate.

        Returns:
            True if account is Raiffeisenbank credit card, False otherwise.
        """
        return (
            account.type_account in ('CreditCard', 'Credit')
            and account.bank == BANK_RAIFFEISENBANK
        )

    def _calculate_purchase_period_for_raiffeisenbank(
        self,
        purchase_month: date | datetime,
    ) -> tuple[datetime, datetime]:
        """Calculate purchase period for Raiffeisenbank.

        Args:
            purchase_month: Month to calculate period for.

        Returns:
            Tuple of (purchase_start, purchase_end) datetimes.
        """
        if isinstance(purchase_month, datetime):
            purchase_start_date = purchase_month.date().replace(day=1)
        else:
            purchase_start_date = purchase_month.replace(day=1)

        purchase_start = timezone.make_aware(
            datetime.combine(purchase_start_date, time.min),
        )
        last_day_of_month = monthrange(
            purchase_start_date.year,
            purchase_start_date.month,
        )[1]
        purchase_end = timezone.make_aware(
            datetime.combine(
                purchase_start_date.replace(day=last_day_of_month),
                time.max,
            ),
        )
        return purchase_start, purchase_end

    def _calculate_first_statement_date(
        self,
        first_purchase: datetime,
    ) -> datetime:
        """Calculate first statement date for Raiffeisenbank.

        Args:
            first_purchase: Date of first purchase.

        Returns:
            First statement date (2nd day of month after purchase).
        """
        first_statement_date = first_purchase.replace(
            day=constants.STATEMENT_DAY_NUMBER,
        )
        if first_statement_date <= first_purchase:
            first_statement_date = (
                first_statement_date + relativedelta(months=constants.ONE)
            ).replace(day=constants.STATEMENT_DAY_NUMBER)
        return first_statement_date

    def _generate_statement_dates(
        self,
        first_statement_date: datetime,
    ) -> list[datetime]:
        """Generate list of statement dates for 3 months.

        Args:
            first_statement_date: First statement date.

        Returns:
            List of 3 statement dates (monthly intervals).
        """
        statement_dates = []
        current_statement_date = first_statement_date
        for _ in range(constants.STATEMENT_DATES_COUNT):
            statement_dates.append(current_statement_date)
            current_statement_date = current_statement_date + relativedelta(
                months=constants.ONE
            )
        return statement_dates

    def _calculate_payment_schedule(
        self,
        statement_dates: list[datetime],
        initial_debt: Decimal,
    ) -> tuple[list[PaymentScheduleStatementDict], Decimal]:
        """Calculate payment schedule for each statement.

        Args:
            statement_dates: List of statement dates.
            initial_debt: Initial debt amount.

        Returns:
            Tuple of (payments_schedule, final_debt).
        """
        payments_schedule: list[PaymentScheduleStatementDict] = []
        outstanding_debt = initial_debt

        for i, statement_date in enumerate(statement_dates):
            min_payment = outstanding_debt * Decimal(
                str(constants.MIN_PAYMENT_PERCENTAGE),
            )
            payment_due_date = statement_date + relativedelta(
                days=constants.PAYMENT_DUE_DAYS,
            )

            payments_schedule.append(
                cast(
                    'PaymentScheduleStatementDict',
                    {
                        'statement_date': statement_date,
                        'payment_due_date': payment_due_date,
                        'remaining_debt': outstanding_debt,
                        'min_payment': min_payment,
                        'statement_number': i + 1,
                    },
                ),
            )

            outstanding_debt = outstanding_debt - min_payment

        return payments_schedule, outstanding_debt

    def _calculate_grace_end_date(self, first_purchase: datetime) -> datetime:
        """Calculate grace end date for Raiffeisenbank.

        Args:
            first_purchase: Date of first purchase.

        Returns:
            Grace period end date (110 days after first purchase).
        """
        grace_end = first_purchase + relativedelta(
            days=constants.GRACE_PERIOD_DAYS_RAIFFEISENBANK,
        )
        return timezone.make_aware(
            datetime.combine(grace_end.date(), time.max),
        )

    def calculate_raiffeisenbank_payment_schedule(
        self,
        account: Account,
        purchase_month: date | datetime,
    ) -> RaiffeisenbankScheduleDict:
        """Calculate payment schedule for Raiffeisenbank credit card.

        Args:
            account: Raiffeisenbank credit card account.
            purchase_month: Month to calculate schedule for.

        Returns:
            Dictionary with payment schedule information. Empty dict if
            account is not eligible.
        """
        if not self._validate_raiffeisenbank_account(account):
            return {}

        purchase_start, purchase_end = (
            self._calculate_purchase_period_for_raiffeisenbank(
                purchase_month,
            )
        )

        first_purchase = self._find_first_purchase_in_month(
            account,
            purchase_start,
        )

        if not first_purchase:
            return {}

        if timezone.is_naive(first_purchase):
            first_purchase = timezone.make_aware(first_purchase)

        first_statement_date = self._calculate_first_statement_date(
            first_purchase,
        )
        statement_dates = self._generate_statement_dates(
            first_statement_date,
        )

        initial_debt = (
            self.get_credit_card_debt(
                account,
                purchase_start,
                purchase_end,
            )
            or 0
        )

        payments_schedule, final_debt = self._calculate_payment_schedule(
            statement_dates,
            Decimal(str(initial_debt)),
        )

        grace_end = self._calculate_grace_end_date(first_purchase)

        return {
            'first_purchase_date': first_purchase,
            'grace_end_date': grace_end,
            'total_initial_debt': Decimal(str(initial_debt)),
            'final_debt': final_debt,
            'payments_schedule': payments_schedule,  # type: ignore[typeddict-item]
            'days_until_grace_end': (
                (grace_end.date() - timezone.now().date()).days
                if timezone.now() <= grace_end
                else constants.ZERO
            ),
            'is_overdue': (
                timezone.now() > grace_end and final_debt > constants.ZERO
            ),
        }
