"""Services for finance account operations."""

from calendar import monthrange
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, TypedDict

from dateutil.relativedelta import relativedelta
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
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_different_accounts,
    validate_positive_amount,
)
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


class GracePeriodInfoDict(TypedDict, total=False):
    """Информация о льготном периоде кредитной карты."""

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
    """Элемент графика платежей."""

    date: datetime
    amount: Decimal


class RaiffeisenbankScheduleDict(TypedDict, total=False):
    """График платежей для Raiffeisenbank."""

    first_purchase_date: datetime
    grace_end_date: datetime
    total_initial_debt: Decimal
    final_debt: Decimal
    payments_schedule: list[PaymentScheduleItemDict]
    days_until_grace_end: int
    is_overdue: bool


class TransferService:
    """Service for handling money transfers between accounts."""

    @staticmethod
    @transaction.atomic
    def transfer_money(
        from_account: Account,
        to_account: Account,
        amount: Decimal,
        user: User,
        exchange_date: datetime | None = None,
        notes: str | None = None,
    ) -> TransferMoneyLog:
        """Transfer money between accounts with validation and logging."""
        validate_positive_amount(amount)
        validate_different_accounts(from_account, to_account)
        validate_account_balance(from_account, amount)

        if from_account.transfer_money(to_account, amount):
            return TransferMoneyLog.objects.create(  # type: ignore[misc]
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
    """Service for account-related operations."""

    @staticmethod
    def get_user_accounts(user: User) -> list[Account]:
        """Get all accounts for a specific user."""
        return list(Account.objects.filter(user=user).select_related('user'))

    @staticmethod
    def get_account_by_id(account_id: int, user: User) -> Account | None:
        """Get a specific account by ID for a user."""
        try:
            return Account.objects.get(id=account_id, user=user)
        except Account.DoesNotExist:
            return None

    @staticmethod
    def get_credit_card_debt(
        account: Account,
        start_date: Any | None = None,
        end_date: Any | None = None,
    ) -> Decimal | None:
        """Calculate credit card debt for a given period."""
        if account.type_account not in (
            ACCOUNT_TYPE_CREDIT_CARD,
            ACCOUNT_TYPE_CREDIT,
        ):
            return None

        expense_qs = Expense.objects.filter(account=account)
        income_qs = Income.objects.filter(account=account)
        receipt_qs = Receipt.objects.filter(account=account)

        if start_date and end_date:
            if isinstance(start_date, date) and not isinstance(
                start_date,
                datetime,
            ):
                start_date_dt = timezone.make_aware(
                    datetime.combine(start_date, time.min),
                )
            else:
                start_date_dt = start_date
            if isinstance(end_date, date) and not isinstance(
                end_date,
                datetime,
            ):
                end_date_dt = timezone.make_aware(
                    datetime.combine(end_date, time.max),
                )
            else:
                end_date_dt = end_date

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

    @staticmethod
    @transaction.atomic
    def apply_receipt_spend(account: Account, amount: Decimal) -> Account:
        """Apply spending by receipt to the account balance with validation."""
        validate_positive_amount(amount)
        validate_account_balance(account, amount)
        account.balance -= amount
        account.save()
        return account

    @staticmethod
    @transaction.atomic
    def refund_to_account(account: Account, amount: Decimal) -> Account:
        """Return money to account balance with validation."""
        validate_positive_amount(amount)
        account.balance += amount
        account.save()
        return account

    @staticmethod
    def _adjust_balance_on_same_account(
        account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        difference = new_total_sum - old_total_sum
        if difference == 0:
            return
        if difference > 0:
            AccountService.apply_receipt_spend(account, difference)
        else:
            AccountService.refund_to_account(account, abs(difference))

    @staticmethod
    def _adjust_balance_on_account_change(
        old_account: Account,
        new_account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        AccountService.refund_to_account(old_account, old_total_sum)
        AccountService.apply_receipt_spend(new_account, new_total_sum)

    @staticmethod
    def _should_adjust_same_account(
        old_account: Account,
        new_account: Account,
    ) -> bool:
        return old_account.pk == new_account.pk

    @staticmethod
    @transaction.atomic
    def reconcile_account_balances(
        old_account: Account,
        new_account: Account,
        old_total_sum: Decimal,
        new_total_sum: Decimal,
    ) -> None:
        """Reconcile account balances when amount or account changes."""
        if AccountService._should_adjust_same_account(old_account, new_account):
            AccountService._adjust_balance_on_same_account(
                old_account,
                old_total_sum,
                new_total_sum,
            )
        else:
            AccountService._adjust_balance_on_account_change(
                old_account,
                new_account,
                old_total_sum,
                new_total_sum,
            )

    @staticmethod
    def _get_first_purchase_in_month(
        account: Account,
        month_start: datetime,
    ) -> datetime | None:
        """Find first purchase date in month for credit card."""
        month_end = timezone.make_aware(
            datetime.combine(
                month_start.replace(
                    day=monthrange(month_start.year, month_start.month)[1],
                ),
                time.max,
            ),
        )

        first_expense = (
            Expense.objects.filter(
                account=account,
                date__range=(month_start, month_end),
            )
            .order_by('date')
            .first()
        )

        first_receipt = (
            Receipt.objects.filter(
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

    @staticmethod
    def _calculate_purchase_period(
        purchase_month: Any,
    ) -> tuple[datetime, datetime]:
        """Calculate purchase period start and end dates."""
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

    @staticmethod
    def _calculate_sberbank_grace_period(
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate grace period for Sberbank credit card."""
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

    @staticmethod
    def _calculate_raiffeisenbank_grace_period(
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate grace period for Raiffeisenbank credit card."""
        first_purchase = AccountService._get_first_purchase_in_month(
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

    @staticmethod
    def _calculate_grace_period_by_bank(
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
    ) -> tuple[datetime, datetime, datetime]:
        """Calculate grace period based on bank type."""
        if account.bank == 'SBERBANK':
            return AccountService._calculate_sberbank_grace_period(
                purchase_start,
                purchase_end,
            )
        if account.bank == 'RAIFFAISENBANK':
            return AccountService._calculate_raiffeisenbank_grace_period(
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

    @staticmethod
    def _calculate_debt_info(
        account: Account,
        purchase_start: datetime,
        purchase_end: datetime,
        payments_start: datetime,
        payments_end: datetime,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Calculate debt information for the period."""
        debt_for_month = AccountService.get_credit_card_debt(
            account,
            purchase_start,
            purchase_end,
        )

        if account.bank in ('SBERBANK', 'RAIFFAISENBANK'):
            payments_for_period = AccountService.get_credit_card_debt(
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

    @staticmethod
    def _ensure_timezone_aware(dt: datetime) -> datetime:
        """Ensure datetime is timezone aware."""
        if hasattr(dt, 'utcoffset') and timezone.is_naive(dt):
            return timezone.make_aware(dt)
        return dt

    @staticmethod
    def calculate_grace_period_info(
        account: Account,
        purchase_month: Any,
    ) -> GracePeriodInfoDict:
        """Calculate grace period information for a credit card."""
        if account.type_account not in (
            ACCOUNT_TYPE_CREDIT_CARD,
            ACCOUNT_TYPE_CREDIT,
        ):
            return {}

        purchase_start, purchase_end = (
            AccountService._calculate_purchase_period(purchase_month)
        )

        grace_end, payments_start, payments_end = (
            AccountService._calculate_grace_period_by_bank(
                account,
                purchase_start,
                purchase_end,
            )
        )

        debt_for_month, payments_for_period, final_debt = (
            AccountService._calculate_debt_info(
                account,
                purchase_start,
                purchase_end,
                payments_start,
                payments_end,
            )
        )

        grace_end = AccountService._ensure_timezone_aware(grace_end)

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

    @staticmethod
    def _validate_raiffeisenbank_account(
        account: Account,
    ) -> bool:
        """Validate if account is eligible
        for Raiffeisenbank payment schedule."""
        return (
            account.type_account in ('CreditCard', 'Credit')
            and account.bank == 'RAIFFAISENBANK'
        )

    @staticmethod
    def _calculate_purchase_period_for_raiffeisenbank(
        purchase_month: Any,
    ) -> tuple[datetime, datetime]:
        """Calculate purchase period for Raiffeisenbank."""
        if isinstance(purchase_month, datetime):
            purchase_start_date = purchase_month.date().replace(day=1)
        elif isinstance(purchase_month, date):
            purchase_start_date = purchase_month.replace(day=1)
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

    @staticmethod
    def _calculate_first_statement_date(first_purchase: datetime) -> datetime:
        """Calculate first statement date for Raiffeisenbank."""
        first_statement_date = first_purchase.replace(
            day=constants.STATEMENT_DAY_NUMBER,
        )
        if first_statement_date <= first_purchase:
            first_statement_date = (
                first_statement_date + relativedelta(months=constants.ONE)
            ).replace(day=constants.STATEMENT_DAY_NUMBER)
        return first_statement_date

    @staticmethod
    def _generate_statement_dates(
        first_statement_date: datetime,
    ) -> list[datetime]:
        """Generate list of statement dates for 3 months."""
        statement_dates = []
        current_date = first_statement_date
        for _ in range(constants.STATEMENT_DATES_COUNT):
            statement_dates.append(current_date)
            current_date = current_date + relativedelta(months=constants.ONE)
        return statement_dates

    @staticmethod
    def _calculate_payment_schedule(
        statement_dates: list[datetime],
        initial_debt: Decimal,
    ) -> tuple[list[dict[str, Any]], Decimal]:
        """Calculate payment schedule for each statement."""
        payments_schedule = []
        remaining_debt = initial_debt

        for i, statement_date in enumerate(statement_dates):
            min_payment = remaining_debt * Decimal(
                str(constants.MIN_PAYMENT_PERCENTAGE),
            )
            payment_due_date = statement_date + relativedelta(
                days=constants.PAYMENT_DUE_DAYS,
            )

            payments_schedule.append(
                {
                    'statement_date': statement_date,
                    'payment_due_date': payment_due_date,
                    'remaining_debt': remaining_debt,
                    'min_payment': min_payment,
                    'statement_number': i + 1,
                },
            )

            remaining_debt = remaining_debt - min_payment

        return payments_schedule, remaining_debt

    @staticmethod
    def _calculate_grace_end_date(first_purchase: datetime) -> datetime:
        """Calculate grace end date for Raiffeisenbank."""
        grace_end = first_purchase + relativedelta(
            days=constants.GRACE_PERIOD_DAYS_RAIFFEISENBANK,
        )
        return timezone.make_aware(
            datetime.combine(grace_end.date(), time.max),
        )

    @staticmethod
    def calculate_raiffeisenbank_payment_schedule(
        account: Account,
        purchase_month: Any,
    ) -> RaiffeisenbankScheduleDict:
        """Calculate payment schedule for Raiffeisenbank credit card."""
        if not AccountService._validate_raiffeisenbank_account(account):
            return {}

        purchase_start, purchase_end = (
            AccountService._calculate_purchase_period_for_raiffeisenbank(
                purchase_month,
            )
        )

        first_purchase = AccountService._get_first_purchase_in_month(
            account,
            purchase_start,
        )

        if not first_purchase:
            return {}

        if timezone.is_naive(first_purchase):
            first_purchase = timezone.make_aware(first_purchase)

        first_statement_date = AccountService._calculate_first_statement_date(
            first_purchase,
        )
        statement_dates = AccountService._generate_statement_dates(
            first_statement_date,
        )

        initial_debt = (
            AccountService.get_credit_card_debt(
                account,
                purchase_start,
                purchase_end,
            )
            or 0
        )

        payments_schedule, final_debt = (
            AccountService._calculate_payment_schedule(
                statement_dates,
                Decimal(str(initial_debt)),
            )
        )

        grace_end = AccountService._calculate_grace_end_date(first_purchase)

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

    @staticmethod
    def get_accounts_for_user_or_group(
        user: User,
        group_id: str | None = None,
    ) -> QuerySet[Account]:
        """
        Get accounts for user or group.

        Args:
            user: User instance
            group_id: Optional group ID filter

        Returns:
            QuerySet of accounts for user or group
        """
        if group_id == 'my':
            return Account.objects.filter(user=user).select_related('user')

        if group_id:
            users_in_group = User.objects.filter(groups__id=group_id).distinct()
            if users_in_group.exists():
                return (
                    Account.objects.filter(user__in=users_in_group)
                    .select_related('user')
                    .distinct()
                )
            return Account.objects.filter(user=user).select_related('user')

        if user.groups.exists():
            users_in_groups = User.objects.filter(
                groups__in=user.groups.values_list('id', flat=True),
            ).distinct()
            return (
                Account.objects.filter(user__in=users_in_groups)
                .select_related('user')
                .distinct()
            )
        return Account.objects.filter(user=user).select_related('user')

    @staticmethod
    def get_sum_all_accounts(accounts: Any) -> Decimal:
        """Calculate total balance for a queryset of accounts."""
        total = sum(acc.balance for acc in accounts)
        return Decimal(str(total))

    @staticmethod
    def get_transfer_money_log(
        user: User,
        limit: int = constants.TRANSFER_MONEY_LOG_LIMIT,
    ) -> Any:
        """Get recent transfer logs for a user."""
        return (
            TransferMoneyLog.objects.filter(user=user)
            .select_related(
                'to_account',
                'from_account',
                'user',
            )
            .order_by(
                '-exchange_date',
            )[:limit]
        )
