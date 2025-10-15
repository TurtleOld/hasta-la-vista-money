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
from hasta_la_vista_money.constants import (
    ACCOUNT_TYPE_CREDIT,
    ACCOUNT_TYPE_CREDIT_CARD,
    RECEIPT_OPERATION_PURCHASE,
    RECEIPT_OPERATION_RETURN,
)
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
        if account.type_account not in (ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_CREDIT):
            return None

        from django.db.models import Q
        from django.db.models.functions import Coalesce

        expense_qs = Expense.objects.filter(account=account)
        income_qs = Income.objects.filter(account=account)
        receipt_qs = Receipt.objects.filter(account=account)

        if start_date and end_date:
            expense_qs = expense_qs.filter(date__range=(start_date, end_date))
            income_qs = income_qs.filter(date__range=(start_date, end_date))
            receipt_qs = receipt_qs.filter(receipt_date__range=(start_date, end_date))

        total_expense = expense_qs.aggregate(total=Sum('amount'))['total'] or 0
        total_income = income_qs.aggregate(total=Sum('amount'))['total'] or 0

        from django.db.models import DecimalField
        
        receipt_aggregation = receipt_qs.aggregate(
            total_expense=Coalesce(
                Sum('total_sum', filter=Q(operation_type=RECEIPT_OPERATION_PURCHASE)), 0,
                output_field=DecimalField()
            ),
            total_return=Coalesce(
                Sum('total_sum', filter=Q(operation_type=RECEIPT_OPERATION_RETURN)), 0,
                output_field=DecimalField()
            ),
        )
        total_receipt_expense = receipt_aggregation['total_expense'] or 0
        total_receipt_return = receipt_aggregation['total_return'] or 0

        debt = (total_expense + total_receipt_expense) - (
            total_income + total_receipt_return
        )
        return debt

    @staticmethod
    def _get_first_purchase_in_month(
        account: Account, month_start: datetime
    ) -> Optional[datetime]:
        """
        Находит дату первой покупки в указанном месяце для кредитной карты.

        Ищет среди расходов и чеков (покупки), возвращает самую раннюю дату.
        Используется для расчёта льготного периода Райффайзенбанка.

        Args:
            account: Счёт для поиска покупок
            month_start: Начало месяца (datetime с днём 1)

        Returns:
            datetime: Дата первой покупки или None, если покупок нет
        """
        month_end = datetime.combine(
            month_start.replace(day=monthrange(month_start.year, month_start.month)[1]),
            time.max,
        )

        # Ищем среди расходов
        first_expense = (
            Expense.objects.filter(
                account=account, date__range=(month_start, month_end)
            )
            .order_by('date')
            .first()
        )

        # Ищем среди чеков (покупки)
        first_receipt = (
            Receipt.objects.filter(
                account=account,
                operation_type=RECEIPT_OPERATION_PURCHASE,
                receipt_date__range=(month_start, month_end),
            )
            .order_by('receipt_date')
            .first()
        )

        # Сравниваем даты и возвращаем самую раннюю
        if first_expense and first_receipt:
            return min(first_expense.date, first_receipt.receipt_date)
        elif first_expense:
            return first_expense.date
        elif first_receipt:
            return first_receipt.receipt_date
        else:
            return None

    @staticmethod
    def calculate_grace_period_info(
        account: Account, purchase_month: Any
    ) -> Dict[str, Any]:
        """
        Calculate grace period information for a credit card.

        Bank-dependent logic:
        - Sberbank: current domain logic applies (1 month for purchases + 3 months for repayment).
        - Raiffeisenbank: 110 days from the first purchase date in the month.
        - Other banks: placeholder for now (repayment due at the end of the purchase month) until specific rules are implemented.
        """
        if account.type_account not in (ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_CREDIT):
            return {}

        purchase_start = purchase_month.replace(day=1)
        last_day = monthrange(purchase_start.year, purchase_start.month)[1]
        purchase_end = datetime.combine(purchase_start.replace(day=last_day), time.max)

        # Для Сбербанка используем текущую доменную логику (1+3 месяца)
        if account.bank == 'SBERBANK':
            grace_end_date = purchase_start + relativedelta(months=3)
            last_day_grace = monthrange(grace_end_date.year, grace_end_date.month)[1]
            grace_end = datetime.combine(
                grace_end_date.replace(day=last_day_grace),
                time.max,
            )
            payments_start = purchase_end + relativedelta(seconds=1)
            payments_end = grace_end
        elif account.bank == 'RAIFFAISENBANK':
            # Для Райффайзенбанка: 110 дней с даты первой покупки
            # Находим первую покупку в месяце для определения точки отсчёта
            first_purchase = AccountService._get_first_purchase_in_month(
                account, purchase_start
            )

            if first_purchase:
                # Отсчитываем 110 дней с даты первой покупки
                grace_end = first_purchase + relativedelta(days=110)
                # Устанавливаем время на конец дня для корректного сравнения
                grace_end = datetime.combine(grace_end.date(), time.max)
            else:
                # Если покупок нет, используем конец месяца как fallback
                grace_end = purchase_end

            # Платежи за период начинаются после окончания месяца покупок
            payments_start = purchase_end + relativedelta(seconds=1)
            payments_end = grace_end
        else:
            grace_end = purchase_end
            payments_start = purchase_end + relativedelta(seconds=1)
            payments_end = grace_end

        debt_for_month = AccountService.get_credit_card_debt(
            account, purchase_start, purchase_end
        )

        if account.bank == 'SBERBANK':
            payments_for_period = AccountService.get_credit_card_debt(
                account, payments_start, payments_end
            )
        elif account.bank == 'RAIFFAISENBANK':
            payments_for_period = AccountService.get_credit_card_debt(
                account, payments_start, payments_end
            )
        else:
            payments_for_period = 0

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

    @staticmethod
    def calculate_raiffeisenbank_payment_schedule(
        account: Account, purchase_month: Any
    ) -> Dict[str, Any]:
        """
        Рассчитывает детальный график платежей для кредитной карты Райффайзенбанка.

        Включает:
        - Даты ежемесячных выписок (2-го числа каждого месяца)
        - Суммы минимальных платежей (3% от остатка)
        - Итоговую сумму долга на конец льготного периода

        Args:
            account: Кредитная карта Райффайзенбанка
            purchase_month: Месяц покупок (datetime)

        Returns:
            Dict с информацией о графике платежей
        """
        if (
            account.type_account not in ('CreditCard', 'Credit')
            or account.bank != 'RAIFFAISENBANK'
        ):
            return {}

        purchase_start = purchase_month.replace(day=1)
        last_day = monthrange(purchase_start.year, purchase_start.month)[1]
        purchase_end = datetime.combine(purchase_start.replace(day=last_day), time.max)

        # Находим первую покупку в месяце
        first_purchase = AccountService._get_first_purchase_in_month(
            account, purchase_start
        )

        if not first_purchase:
            return {}

        # Рассчитываем даты выписок (2-го числа каждого месяца, начиная со следующего)
        first_statement_date = first_purchase.replace(day=2)
        if first_statement_date <= first_purchase:
            # Если 2-е число уже прошло, берём следующий месяц
            first_statement_date = (
                first_statement_date + relativedelta(months=1)
            ).replace(day=2)

        # Рассчитываем даты трёх выписок
        statement_dates = []
        current_date = first_statement_date
        for i in range(3):
            statement_dates.append(current_date)
            current_date = current_date + relativedelta(months=1)

        # Рассчитываем минимальные платежи и остатки
        payments_schedule = []
        remaining_debt = (
            AccountService.get_credit_card_debt(account, purchase_start, purchase_end)
            or 0
        )

        for i, statement_date in enumerate(statement_dates):
            # Минимальный платёж 3% от остатка
            min_payment = remaining_debt * Decimal('0.03')

            # Срок оплаты - 20 дней с даты выписки
            payment_due_date = statement_date + relativedelta(days=20)

            payments_schedule.append(
                {
                    'statement_date': statement_date,
                    'payment_due_date': payment_due_date,
                    'remaining_debt': remaining_debt,
                    'min_payment': min_payment,
                    'statement_number': i + 1,
                }
            )

            # Остаток после минимального платежа
            remaining_debt = remaining_debt - min_payment

        # Конец льготного периода (110 дней с первой покупки)
        grace_end = first_purchase + relativedelta(days=110)
        grace_end = datetime.combine(grace_end.date(), time.max)

        return {
            'first_purchase_date': first_purchase,
            'grace_end_date': grace_end,
            'total_initial_debt': AccountService.get_credit_card_debt(
                account, purchase_start, purchase_end
            )
            or 0,
            'final_debt': remaining_debt,  # Остаток после всех минимальных платежей
            'payments_schedule': payments_schedule,
            'days_until_grace_end': (
                (grace_end.date() - timezone.now().date()).days
                if timezone.now() <= grace_end
                else 0
            ),
            'is_overdue': timezone.now() > grace_end and remaining_debt > 0,
        }


def get_accounts_for_user_or_group(user, group_id=None):
    if not group_id or group_id == 'my':
        return Account.objects.filter(user=user).select_related('user')
    else:
        users_in_group = User.objects.filter(groups__id=group_id)
        return Account.objects.filter(user__in=users_in_group).select_related('user')


def get_sum_all_accounts(accounts):
    """Calculate total balance for a queryset of accounts."""
    return sum(acc.balance for acc in accounts)


def get_transfer_money_log(user, limit=10):
    """Get recent transfer logs for a user."""
    return TransferMoneyLog.objects.filter(user=user).order_by('-exchange_date')[:limit]
