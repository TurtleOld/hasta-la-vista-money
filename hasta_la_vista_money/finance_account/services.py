"""Services for finance account operations."""

from calendar import monthrange
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict, cast

from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.db.models.query import QuerySet
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT,
    ACCOUNT_TYPE_CREDIT_CARD,
    RECEIPT_OPERATION_PURCHASE,
    RECEIPT_OPERATION_RETURN,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_different_accounts,
    validate_positive_amount,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.repositories import ExpenseRepository
    from hasta_la_vista_money.finance_account.repositories import (
        AccountRepository,
        TransferMoneyLogRepository,
    )
    from hasta_la_vista_money.income.repositories import IncomeRepository
    from hasta_la_vista_money.receipts.repositories import ReceiptRepository


class GracePeriodInfoDict(TypedDict, total=False):
    """Information about credit card grace period.

    Attributes:
        purchase_month: Purchase month in MM.YYYY format.
        purchase_start: Start date of purchase period.
        purchase_end: End date of purchase period.
        grace_end: End date of grace period.
        debt_for_month: Debt amount for the purchase month.
        payments_for_period: Payments made during the grace period.
        final_debt: Final debt amount after grace period.
        is_overdue: Whether the debt is overdue.
        days_until_due: Number of days until payment is due.
    """

    purchase_month: str
    purchase_start: datetime
    purchase_end: datetime
    grace_end: datetime
    debt_for_month: Decimal
    payments_for_period: Decimal
    final_debt: Decimal
    is_overdue: bool
    days_until_due: int


class PaymentScheduleItemDict(TypedDict):
    """Payment schedule item.

    Attributes:
        date: Payment date.
        amount: Payment amount.
    """

    date: datetime
    amount: Decimal


class PaymentScheduleStatementDict(TypedDict):
    """Payment schedule statement item.

    Attributes:
        statement_date: Statement date.
        payment_due_date: Payment due date.
        remaining_debt: Remaining debt amount.
        min_payment: Minimum payment amount.
        statement_number: Statement number.
    """

    statement_date: datetime
    payment_due_date: datetime
    remaining_debt: Decimal
    min_payment: Decimal
    statement_number: int


class RaiffeisenbankScheduleDict(TypedDict, total=False):
    """Payment schedule for Raiffeisenbank credit card.

    Attributes:
        first_purchase_date: Date of first purchase in the period.
        grace_end_date: End date of grace period.
        total_initial_debt: Total initial debt amount.
        final_debt: Final debt amount after payments.
        payments_schedule: List of payment schedule statements.
        days_until_grace_end: Number of days until grace period ends.
        is_overdue: Whether the debt is overdue.
    """

    first_purchase_date: datetime
    grace_end_date: datetime
    total_initial_debt: Decimal
    final_debt: Decimal
    payments_schedule: list[PaymentScheduleItemDict]
    days_until_grace_end: int
    is_overdue: bool


class TransferService:
    """Service for handling money transfers between accounts.

    This service handles money transfers between user accounts with validation,
    balance updates, and transaction logging.
    """

    def __init__(
        self,
        transfer_money_log_repository: 'TransferMoneyLogRepository',
    ) -> None:
        """Initialize TransferService.

        Args:
            transfer_money_log_repository: Repository for transfer log
                operations.
        """
        self.transfer_money_log_repository = transfer_money_log_repository

    @transaction.atomic
    def transfer_money(
        self,
        from_account: Account,
        to_account: Account,
        amount: Decimal,
        user: User,
        exchange_date: datetime | None = None,
        notes: str | None = None,
    ) -> TransferMoneyLog:
        """Transfer money between accounts with validation and logging.

        Args:
            from_account: Source account for the transfer.
            to_account: Destination account for the transfer.
            amount: Amount to transfer. Must be positive.
            user: User performing the transfer.
            exchange_date: Optional exchange date for the transfer.
            notes: Optional notes for the transfer.

        Returns:
            TransferMoneyLog: Created transfer log entry.

        Raises:
            ValueError: If transfer fails due to insufficient funds or
                invalid accounts.
        """
        validate_positive_amount(amount)
        validate_different_accounts(from_account, to_account)
        validate_account_balance(from_account, amount)

        if from_account.transfer_money(to_account, amount):
            return self.transfer_money_log_repository.create_log(
                user=user,
                from_account=from_account,
                to_account=to_account,
                amount=amount,
                exchange_date=exchange_date,
                notes=notes or '',
            )

        error_msg = 'Transfer failed - insufficient funds or invalid accounts'
        raise ValueError(error_msg)


class AccountService:
    """Service for account-related operations.

    Handles account management, balance operations, credit card calculations,
    and grace period information.
    """

    def __init__(
        self,
        account_repository: 'AccountRepository',
        transfer_money_log_repository: 'TransferMoneyLogRepository',
        expense_repository: 'ExpenseRepository',
        income_repository: 'IncomeRepository',
        receipt_repository: 'ReceiptRepository',
    ) -> None:
        """Initialize AccountService.

        Args:
            account_repository: Repository for account data access.
            transfer_money_log_repository: Repository for transfer log
                operations.
            expense_repository: Repository for expense data access.
            income_repository: Repository for income data access.
            receipt_repository: Repository for receipt data access.
        """
        self.account_repository = account_repository
        self.transfer_money_log_repository = transfer_money_log_repository
        self.expense_repository = expense_repository
        self.income_repository = income_repository
        self.receipt_repository = receipt_repository

    def get_user_accounts(self, user: User) -> list[Account]:
        """Get all accounts for a specific user.

        Args:
            user: User instance to get accounts for.

        Returns:
            List of Account instances for the user.
        """
        return list(self.account_repository.get_by_user_with_related(user))

    def get_account_by_id(self, account_id: int, user: User) -> Account | None:
        """Get a specific account by ID for a user.

        Args:
            account_id: ID of the account to retrieve.
            user: User instance to verify ownership.

        Returns:
            Account instance if found and owned by user, None otherwise.
        """
        return self.account_repository.get_by_id_and_user(account_id, user)

    def get_credit_card_debt(
        self,
        account: Account,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
    ) -> Decimal | None:
        """Calculate credit card debt for a given period.

        Calculates the debt by summing expenses and receipts (purchases)
        and subtracting income and returns for the specified period.

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

        expense_qs = self.expense_repository.filter(account=account)
        income_qs = self.income_repository.filter(account=account)
        receipt_qs = self.receipt_repository.filter(account=account)

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

            expense_qs = expense_qs.filter(
                date__range=(start_date_dt, end_date_dt),
            )
            income_qs = income_qs.filter(
                date__range=(start_date_dt, end_date_dt),
            )
            receipt_qs = receipt_qs.filter(
                receipt_date__range=(start_date_dt, end_date_dt),
            )

        total_expense = expense_qs.aggregate(total=Sum('amount'))['total'] or 0
        total_income = income_qs.aggregate(total=Sum('amount'))['total'] or 0

        receipt_aggregation = receipt_qs.aggregate(
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

    def apply_receipt_spend(self, account: Account, amount: Decimal) -> Account:
        """Apply spending by receipt to the account balance with validation.

        Args:
            account: Account to apply spending to.
            amount: Amount to subtract from balance. Must be positive.

        Returns:
            Updated Account instance.

        Raises:
            ValidationError: If amount is invalid or account has
                insufficient funds.
        """
        validate_positive_amount(amount)
        validate_account_balance(account, amount)
        account.balance -= amount
        account.save()
        return account

    def refund_to_account(self, account: Account, amount: Decimal) -> Account:
        """Return money to account balance with validation.

        Args:
            account: Account to refund to.
            amount: Amount to add to balance. Must be positive.

        Returns:
            Updated Account instance.

        Raises:
            ValidationError: If amount is invalid.
        """
        validate_positive_amount(amount)
        account.balance += amount
        account.save()
        return account

    def _adjust_balance_on_same_account(
        self,
        account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """Adjust balance when transaction amount changes on same account.

        Args:
            account: Account to adjust balance for.
            old_total_sum: Previous transaction amount.
            new_total_sum: New transaction amount.
        """
        difference = new_total_sum - old_total_sum
        if difference == 0:
            return
        if difference > 0:
            self.apply_receipt_spend(account, difference)
        else:
            self.refund_to_account(account, abs(difference))

    def _adjust_balance_on_account_change(
        self,
        old_account: Account,
        new_account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """Adjust balance when transaction account changes.

        Args:
            old_account: Previous account.
            new_account: New account.
            old_total_sum: Previous transaction amount.
            new_total_sum: New transaction amount.
        """
        self.refund_to_account(old_account, old_total_sum)
        self.apply_receipt_spend(new_account, new_total_sum)

    def _should_adjust_same_account(
        self,
        old_account: Account,
        new_account: Account,
    ) -> bool:
        """Check if both accounts are the same.

        Args:
            old_account: Previous account.
            new_account: New account.

        Returns:
            True if accounts are the same, False otherwise.
        """
        return old_account.pk == new_account.pk

    def reconcile_account_balances(
        self,
        old_account: Account,
        new_account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """Reconcile account balances when amount or account changes.

        Handles two scenarios:
        1. Same account: adjusts balance by difference
        2. Different accounts: refunds old account, applies to new account

        Args:
            old_account: Account before change.
            new_account: Account after change.
            old_total_sum: Total amount before change.
            new_total_sum: Total amount after change.
        """
        if self._should_adjust_same_account(old_account, new_account):
            self._adjust_balance_on_same_account(
                old_account,
                old_total_sum,
                new_total_sum,
            )
        else:
            self._adjust_balance_on_account_change(
                old_account,
                new_account,
                old_total_sum,
                new_total_sum,
            )

    def _get_first_purchase_in_month(
        self,
        account: Account,
        month_start: datetime,
    ) -> datetime | None:
        """Find first purchase date in month for credit card.

        Searches for the earliest expense or receipt purchase in the
        given month.

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
            return cast(
                'datetime | None',
                min(first_expense.date, first_receipt.receipt_date),
            )
        if first_expense:
            return cast('datetime | None', first_expense.date)
        if first_receipt:
            return cast('datetime | None', first_receipt.receipt_date)
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
        last_day = monthrange(purchase_start.year, purchase_start.month)[1]
        purchase_end = timezone.make_aware(
            datetime.combine(
                purchase_start.date().replace(day=last_day),
                time.max,
            ),
        )

        return purchase_start, purchase_end

    def _calculate_sberbank_grace_period(
        self,
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate grace period for Sberbank credit card.

        Args:
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

    def _calculate_raiffeisenbank_grace_period(
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

    def _calculate_grace_period_by_bank(
        self,
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate grace period based on bank type.

        Args:
            account: Account to calculate grace period for.
            purchase_start: Start of purchase period.
            purchase_end: End of purchase period.

        Returns:
            Tuple of (grace_end, payments_start, payments_end) datetimes.
        """
        if account.bank == 'SBERBANK':
            return self._calculate_sberbank_grace_period(
                purchase_start,
                purchase_end,
            )
        if account.bank == 'RAIFFAISENBANK':
            return self._calculate_raiffeisenbank_grace_period(
                account,
                purchase_start,
                purchase_end,
            )
        grace_end = purchase_end
        payments_start = purchase_end + relativedelta(
            seconds=constants.ONE_SECOND,
        )
        payments_end = grace_end
        return grace_end, payments_start, payments_end

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
            Tuple of (debt_for_month, payments_for_period, final_debt).
        """
        debt_for_month = self.get_credit_card_debt(
            account,
            purchase_start,
            purchase_end,
        )

        if account.bank in ('SBERBANK', 'RAIFFAISENBANK'):
            payments_for_period = self.get_credit_card_debt(
                account,
                payments_start,
                payments_end,
            )
        else:
            payments_for_period = Decimal(str(constants.ZERO))

        final_debt = (debt_for_month or constants.ZERO) + (
            payments_for_period or constants.ZERO
        )

        return (  # type: ignore[return-value]
            debt_for_month or constants.ZERO,
            payments_for_period or constants.ZERO,
            final_debt,
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

        debt_for_month, payments_for_period, final_debt = (
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
            'debt_for_month': debt_for_month,
            'payments_for_period': payments_for_period,
            'final_debt': final_debt,
            'is_overdue': (
                timezone.now() > grace_end and final_debt > constants.ZERO
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
            and account.bank == 'RAIFFAISENBANK'
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
        last_day = monthrange(
            purchase_start_date.year,
            purchase_start_date.month,
        )[1]
        purchase_end = timezone.make_aware(
            datetime.combine(
                purchase_start_date.replace(day=last_day),
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
        current_date = first_statement_date
        for _ in range(constants.STATEMENT_DATES_COUNT):
            statement_dates.append(current_date)
            current_date = current_date + relativedelta(months=constants.ONE)
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
        remaining_debt = initial_debt

        for i, statement_date in enumerate(statement_dates):
            min_payment = remaining_debt * Decimal(
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
                        'remaining_debt': remaining_debt,
                        'min_payment': min_payment,
                        'statement_number': i + 1,
                    },
                ),
            )

            remaining_debt = remaining_debt - min_payment

        return payments_schedule, remaining_debt

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

        first_purchase = self._get_first_purchase_in_month(
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

    def get_users_for_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> list[User]:
        """
        Get list of users for a specific group or user.

        Common logic for group filtering used across the application.
        Handles 'my', None, and group ID cases.

        Args:
            user: Current user instance
            group_id: Optional group ID filter:
                - 'my' or None: return only current user
                - group ID (str): return all users in the group

        Returns:
            List of User instances for the specified group or user.

        Raises:
            Group.DoesNotExist: If group_id is provided but group doesn't exist
                (should be handled by caller)
        """
        if not group_id or group_id == 'my':
            return [user]

        try:
            group = Group.objects.get(pk=group_id)
        except Group.DoesNotExist:
            return []
        else:
            return list(group.user_set.all())

    def get_accounts_for_user_or_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> QuerySet[Account]:
        """Get accounts for user or group.

        Args:
            user: User instance.
            group_id: Optional group ID filter.

        Returns:
            QuerySet of accounts for user or group.
        """
        return self.account_repository.get_by_user_and_group(user, group_id)

    def get_sum_all_accounts(self, accounts: QuerySet[Account]) -> Decimal:
        """Calculate total balance for a queryset of accounts.

        Args:
            accounts: QuerySet of accounts to sum.

        Returns:
            Total balance as Decimal.
        """
        total = sum(acc.balance for acc in accounts)
        return Decimal(str(total))

    def get_transfer_money_log(
        self,
        user: User,
        limit: int = constants.TRANSFER_MONEY_LOG_LIMIT,
    ) -> QuerySet[TransferMoneyLog]:
        """Get recent transfer logs for a user.

        Args:
            user: User to get transfer logs for.
            limit: Maximum number of logs to return.

        Returns:
            QuerySet of transfer logs ordered by date descending.
        """
        return self.transfer_money_log_repository.get_by_user_ordered(
            user,
            limit,
        )
