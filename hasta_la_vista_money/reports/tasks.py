"""Reports tasks module.

This module provides Celery tasks for generating monthly, yearly,
and user statistics reports.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import structlog
from celery import shared_task
from django.db.models import Avg, Count, Max, Min, Sum
from django.db.models.functions import TruncMonth

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.reporting import (
    actual_interest_totals,
    actual_interest_totals_by_month,
)
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


@shared_task(  # type: ignore[untyped-decorator]
    name='reports.generate_monthly_report',
)
def generate_monthly_report(
    user_id: int,
    year: int,
    month: int,
) -> dict[str, Any]:
    """Generate monthly report for user."""
    logger.info(
        'Starting monthly report generation',
        user_id=user_id,
        year=year,
        month=month,
    )

    try:
        user = User.objects.get(id=user_id)

        start_date = datetime(year, month, 1, tzinfo=UTC)
        if month == constants.NUMBER_TWELFTH_MONTH_YEAR:
            end_date = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end_date = datetime(year, month + 1, 1, tzinfo=UTC)

        logger.info(
            'Report period defined',
            user_id=user_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        income_stats = Transaction.objects.filter(
            user=user,
            type=TransactionType.INCOME,
            date__gte=start_date,
            date__lt=end_date,
        ).aggregate(
            transaction_total=Sum('amount'),
            transaction_count=Count('id'),
            transaction_average=Avg('amount'),
            transaction_minimum=Min('amount'),
            transaction_maximum=Max('amount'),
        )

        expense_stats = Transaction.objects.filter(
            user=user,
            type=TransactionType.EXPENSE,
            date__gte=start_date,
            date__lt=end_date,
        ).aggregate(
            transaction_total=Sum('amount'),
            transaction_count=Count('id'),
            transaction_average=Avg('amount'),
            transaction_minimum=Min('amount'),
            transaction_maximum=Max('amount'),
        )
        interest_income, interest_expense = actual_interest_totals(
            [user],
            start_date.date(),
            (end_date - timedelta(days=1)).date(),
        )
        income_stats['total_income'] = (
            Decimal(
                income_stats['transaction_total'] or constants.ZERO,
            )
            + interest_income
        )
        income_stats['deposit_interest_income'] = interest_income
        expense_stats['total_expense'] = (
            Decimal(
                expense_stats['transaction_total'] or constants.ZERO,
            )
            + interest_expense
        )
        expense_stats['deposit_interest_expense'] = interest_expense

        top_income_qs = (
            Transaction.objects.filter(
                user=user,
                type=TransactionType.INCOME,
                date__gte=start_date,
                date__lt=end_date,
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
                count=Count('id'),
            )
            .order_by('-total')[:5]
        )
        top_income_categories = cast(
            'list[dict[str, Any]]',
            list(top_income_qs),
        )

        top_expense_qs = (
            Transaction.objects.filter(
                user=user,
                type=TransactionType.EXPENSE,
                date__gte=start_date,
                date__lt=end_date,
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
                count=Count('id'),
            )
            .order_by('-total')[:5]
        )
        top_expense_categories = cast(
            'list[dict[str, Any]]',
            list(top_expense_qs),
        )

        receipt_stats = Receipt.objects.filter(
            user=user,
            receipt_date__gte=start_date,
            receipt_date__lt=end_date,
        ).aggregate(
            total_receipts=Count('id'),
            total_receipt_sum=Sum('total_sum'),
            avg_receipt_sum=Avg('total_sum'),
        )

        top_sellers_qs = (
            Receipt.objects.filter(
                user=user,
                receipt_date__gte=start_date,
                receipt_date__lt=end_date,
            )
            .values('seller__name_seller')
            .annotate(
                total=Sum('total_sum'),
                count=Count('id'),
            )
            .order_by('-total')[:5]
        )
        top_sellers = cast('list[dict[str, Any]]', list(top_sellers_qs))

        summary = {
            'net_income': (income_stats['total_income'] or 0)
            - (expense_stats['total_expense'] or 0),
            'savings_rate': (
                (
                    (income_stats['total_income'] or 0)
                    - (expense_stats['total_expense'] or 0)
                )
                / (income_stats['total_income'] or 1)
                * 100
            )
            if income_stats['total_income']
            else 0,
        }

        report_data = {
            'period': {
                'year': year,
                'month': month,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
            },
            'income': income_stats,
            'expense': expense_stats,
            'receipts': receipt_stats,
            'top_income_categories': list(top_income_categories),
            'top_expense_categories': list(top_expense_categories),
            'top_sellers': list(top_sellers),
            'summary': summary,
        }

        logger.info(
            'Monthly report generated successfully',
            user_id=user_id,
            year=year,
            month=month,
            total_income=str(income_stats['total_income']),
            total_expense=str(expense_stats['total_expense']),
            net_income=str(summary['net_income']),
            receipts_count=receipt_stats['total_receipts'],
        )

    except Exception as e:
        logger.exception(
            'Error generating monthly report',
            user_id=user_id,
            year=year,
            month=month,
            error=str(e),
        )
        return {'success': False, 'error': str(e)}
    else:
        return {'success': True, 'report': report_data}


@shared_task(  # type: ignore[untyped-decorator]
    name='reports.generate_yearly_report',
)
def generate_yearly_report(
    user_id: int,
    year: int,
) -> dict[str, Any]:
    """Generate yearly report for user."""
    logger.info(
        'Starting yearly report generation',
        user_id=user_id,
        year=year,
    )

    try:
        user = User.objects.get(id=user_id)

        start_date = datetime(year, 1, 1, tzinfo=UTC)
        end_date = datetime(year + 1, 1, 1, tzinfo=UTC)

        logger.info(
            'Yearly report period defined',
            user_id=user_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        monthly_totals: dict[int, dict[str, Decimal]] = defaultdict(
            lambda: {
                TransactionType.INCOME: Decimal(0),
                TransactionType.EXPENSE: Decimal(0),
            },
        )
        monthly_rows = (
            Transaction.objects.filter(user=user, date__year=year)
            .annotate(month=TruncMonth('date'))
            .values('month', 'type')
            .annotate(total=Sum('amount'))
        )
        for row in monthly_rows:
            month_value = row['month']
            if month_value is None:
                continue
            month_number = month_value.month
            monthly_totals[month_number][row['type']] = row['total'] or Decimal(
                0,
            )

        monthly_interest = actual_interest_totals_by_month(user, year)
        monthly_data = []
        for month in range(
            constants.NUMBER_FIRST_MONTH_YEAR,
            constants.NUMBER_TWELFTH_MONTH_YEAR + 1,
        ):
            month_income = monthly_totals[month][TransactionType.INCOME]
            month_expense = monthly_totals[month][TransactionType.EXPENSE]
            interest_income, interest_expense = monthly_interest.get(
                month,
                (Decimal(), Decimal()),
            )
            month_income += interest_income
            month_expense += interest_expense

            monthly_data.append(
                {
                    'month': month,
                    'income': month_income,
                    'expense': month_expense,
                    'net': month_income - month_expense,
                },
            )

        yearly_income = Transaction.objects.filter(
            user=user,
            type=TransactionType.INCOME,
            date__year=year,
        ).aggregate(
            transaction_total=Sum('amount'),
            transaction_count=Count('id'),
            transaction_average=Avg('amount'),
        )

        yearly_expense = Transaction.objects.filter(
            user=user,
            type=TransactionType.EXPENSE,
            date__year=year,
        ).aggregate(
            transaction_total=Sum('amount'),
            transaction_count=Count('id'),
            transaction_average=Avg('amount'),
        )
        interest_income = sum(
            (totals[0] for totals in monthly_interest.values()),
            start=Decimal(),
        )
        interest_expense = sum(
            (totals[1] for totals in monthly_interest.values()),
            start=Decimal(),
        )
        yearly_income['total'] = (
            Decimal(
                yearly_income['transaction_total'] or constants.ZERO,
            )
            + interest_income
        )
        yearly_income['deposit_interest'] = interest_income
        yearly_expense['total'] = (
            Decimal(
                yearly_expense['transaction_total'] or constants.ZERO,
            )
            + interest_expense
        )
        yearly_expense['deposit_interest'] = interest_expense

        top_income_year_qs = (
            Transaction.objects.filter(
                user=user,
                type=TransactionType.INCOME,
                date__year=year,
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
            )
            .order_by('-total')[:10]
        )
        top_income_categories = cast(
            'list[dict[str, Any]]',
            list(top_income_year_qs),
        )

        top_expense_year_qs = (
            Transaction.objects.filter(
                user=user,
                type=TransactionType.EXPENSE,
                date__year=year,
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
            )
            .order_by('-total')[:10]
        )
        top_expense_categories = cast(
            'list[dict[str, Any]]',
            list(top_expense_year_qs),
        )

        summary = {
            'total_income': yearly_income['total'] or 0,
            'total_expense': yearly_expense['total'] or 0,
            'net_income': (yearly_income['total'] or 0)
            - (yearly_expense['total'] or 0),
            'savings_rate': (
                ((yearly_income['total'] or 0) - (yearly_expense['total'] or 0))
                / (yearly_income['total'] or 1)
                * 100
            )
            if yearly_income['total']
            else 0,
        }

        report_data = {
            'year': year,
            'monthly_data': monthly_data,
            'yearly_income': yearly_income,
            'yearly_expense': yearly_expense,
            'top_income_categories': list(top_income_categories),
            'top_expense_categories': list(top_expense_categories),
            'summary': summary,
        }

        logger.info(
            'Yearly report generated successfully',
            user_id=user_id,
            year=year,
            total_income=str(yearly_income['total']),
            total_expense=str(yearly_expense['total']),
            net_income=str(summary['net_income']),
            transactions_count=(yearly_income['transaction_count'] or 0)
            + (yearly_expense['transaction_count'] or 0),
        )

    except Exception as e:
        logger.exception(
            'Error generating yearly report',
            user_id=user_id,
            year=year,
            error=str(e),
        )
        return {'success': False, 'error': str(e)}
    else:
        return {'success': True, 'report': report_data}


@shared_task(  # type: ignore[untyped-decorator]
    name='reports.generate_user_statistics',
)
def generate_user_statistics(
    user_id: int,
) -> dict[str, Any]:
    """Generate overall user statistics."""
    logger.info(
        'Starting user statistics generation',
        user_id=user_id,
    )

    try:
        user = User.objects.get(id=user_id)

        total_income = Transaction.objects.filter(
            user=user,
            type=TransactionType.INCOME,
        ).aggregate(
            transaction_total=Sum('amount'),
            transaction_count=Count('id'),
            transaction_average=Avg('amount'),
        )

        total_expense = Transaction.objects.filter(
            user=user,
            type=TransactionType.EXPENSE,
        ).aggregate(
            transaction_total=Sum('amount'),
            transaction_count=Count('id'),
            transaction_average=Avg('amount'),
        )
        transaction_income_total = Decimal(
            total_income['transaction_total'] or constants.ZERO,
        )
        transaction_expense_total = Decimal(
            total_expense['transaction_total'] or constants.ZERO,
        )
        interest_income, interest_expense = actual_interest_totals([user])
        total_income['total'] = transaction_income_total + interest_income
        total_income['deposit_interest'] = interest_income
        total_expense['total'] = transaction_expense_total + interest_expense
        total_expense['deposit_interest'] = interest_expense

        total_receipts = Receipt.objects.filter(user=user).aggregate(
            total=Sum('total_sum'),
            count=Count('id'),
            avg=Avg('total_sum'),
        )

        income_cat_qs = (
            Transaction.objects.filter(
                user=user,
                type=TransactionType.INCOME,
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
                count=Count('id'),
            )
            .order_by('-total')[:10]
        )
        income_categories = cast(
            'list[dict[str, Any]]',
            list(income_cat_qs),
        )

        expense_cat_qs = (
            Transaction.objects.filter(
                user=user,
                type=TransactionType.EXPENSE,
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
                count=Count('id'),
            )
            .order_by('-total')[:10]
        )
        expense_categories = cast(
            'list[dict[str, Any]]',
            list(expense_cat_qs),
        )

        first_income = Transaction.objects.filter(
            user=user,
            type=TransactionType.INCOME,
        ).aggregate(
            first_date=Min('date'),
            last_date=Max('date'),
        )

        first_expense = Transaction.objects.filter(
            user=user,
            type=TransactionType.EXPENSE,
        ).aggregate(
            first_date=Min('date'),
            last_date=Max('date'),
        )

        summary = {
            'net_worth': (total_income['total'] or 0)
            - (total_expense['total'] or 0),
            'total_transactions': (total_income['transaction_count'] or 0)
            + (total_expense['transaction_count'] or 0),
            'avg_transaction': (
                (transaction_income_total + transaction_expense_total)
                / (
                    (total_income['transaction_count'] or 0)
                    + (total_expense['transaction_count'] or 0)
                )
            )
            if (
                (total_income['transaction_count'] or 0)
                + (total_expense['transaction_count'] or 0)
                > 0
            )
            else 0,
        }

        stats_data = {
            'user_id': user_id,
            'income': total_income,
            'expense': total_expense,
            'receipts': total_receipts,
            'top_income_categories': list(income_categories),
            'top_expense_categories': list(expense_categories),
            'time_periods': {
                'income': first_income,
                'expense': first_expense,
            },
            'summary': summary,
        }

        logger.info(
            'User statistics generated successfully',
            user_id=user_id,
            total_income=str(total_income['total']),
            total_expense=str(total_expense['total']),
            net_worth=str(summary['net_worth']),
            total_transactions=summary['total_transactions'],
            receipts_count=total_receipts['count'],
        )

    except Exception as e:
        logger.exception(
            'Error generating user statistics',
            user_id=user_id,
            error=str(e),
        )
        return {'success': False, 'error': str(e)}
    else:
        return {'success': True, 'statistics': stats_data}
