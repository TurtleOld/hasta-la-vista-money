"""Модуль задач для пакета reports."""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db.models import Avg, Count, Max, Min, Sum

from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User

logger = structlog.get_logger(__name__)


async def generate_monthly_report(
    user_id: int,
    year: int,
    month: int,
) -> dict[str, Any]:
    """
    Генерация месячного отчета для пользователя.

    Args:
        user_id: ID пользователя
        year: Год
        month: Месяц
        context: Контекст задачи

    Returns:
        Месячный отчет
    """
    logger.info(
        'Starting monthly report generation',
        user_id=user_id,
        year=year,
        month=month,
    )

    try:
        user = await User.objects.aget(id=user_id)

        # Определяем период
        start_date = datetime(year, month, 1, tzinfo=UTC)
        if month == constants.NUMBER_TWELFTH_MONTH_YEAR:
            end_date = datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1, tzinfo=UTC) - timedelta(
                days=1,
            )

        logger.info(
            'Report period defined',
            user_id=user_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        # Статистика по доходам
        income_stats = await Income.objects.filter(
            user=user,
            date__range=(start_date, end_date),
        ).aaggregate(
            total_income=Sum('amount'),
            income_count=Count('id'),
            avg_income=Avg('amount'),
            min_income=Min('amount'),
            max_income=Max('amount'),
        )

        # Статистика по расходам
        expense_stats = await Expense.objects.filter(
            user=user,
            date__range=(start_date, end_date),
        ).aaggregate(
            total_expense=Sum('amount'),
            expense_count=Count('id'),
            avg_expense=Avg('amount'),
            min_expense=Min('amount'),
            max_expense=Max('amount'),
        )

        # Топ категорий доходов
        top_income_qs = (
            Income.objects.filter(
                user=user,
                date__range=(start_date, end_date),
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
                count=Count('id'),
            )
            .order_by('-total')[:5]
        )
        top_income_categories: list[dict[str, Any]] = await sync_to_async(
            lambda: list(top_income_qs),
        )()  # type: ignore[misc]

        # Топ категорий расходов
        top_expense_qs = (
            Expense.objects.filter(
                user=user,
                date__range=(start_date, end_date),
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
                count=Count('id'),
            )
            .order_by('-total')[:5]
        )
        top_expense_categories: list[dict[str, Any]] = await sync_to_async(
            lambda: list(top_expense_qs),
        )()  # type: ignore[misc]

        # Статистика по чекам
        receipt_stats = await Receipt.objects.filter(
            user=user,
            receipt_date__range=(start_date, end_date),
        ).aaggregate(
            total_receipts=Count('id'),
            total_receipt_sum=Sum('total_sum'),
            avg_receipt_sum=Avg('total_sum'),
        )

        # Топ продавцов
        top_sellers_qs = (
            Receipt.objects.filter(
                user=user,
                receipt_date__range=(start_date, end_date),
            )
            .values('seller__name_seller')
            .annotate(
                total=Sum('total_sum'),
                count=Count('id'),
            )
            .order_by('-total')[:5]
        )
        top_sellers: list[dict[str, Any]] = await sync_to_async(
            lambda: list(top_sellers_qs),
        )()  # type: ignore[misc]

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
            'summary': {
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
            },
        }

        logger.info(
            'Monthly report generated successfully',
            user_id=user_id,
            year=year,
            month=month,
            total_income=str(income_stats['total_income']),  # type: ignore[index]
            total_expense=str(expense_stats['total_expense']),  # type: ignore[index]
            net_income=str(report_data['summary']['net_income']),  # type: ignore[index]
            receipts_count=receipt_stats['total_receipts'],  # type: ignore[index]
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


async def generate_yearly_report(
    user_id: int,
    year: int,
) -> dict[str, Any]:
    """
    Генерация годового отчета для пользователя.

    Args:
        user_id: ID пользователя
        year: Год
        context: Контекст задачи

    Returns:
        Годовой отчет
    """
    logger.info(
        'Starting yearly report generation',
        user_id=user_id,
        year=year,
    )

    try:
        user = await User.objects.aget(id=user_id)

        start_date = datetime(year, 1, 1, tzinfo=UTC)
        end_date = datetime(year, 12, 31, tzinfo=UTC)

        logger.info(
            'Yearly report period defined',
            user_id=user_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        monthly_data = []
        for month in range(
            constants.NUMBER_FIRST_MONTH_YEAR,
            constants.NUMBER_TWELFTH_MONTH_YEAR + 1,
        ):
            month_start = datetime(year, month, 1, tzinfo=UTC)
            if month == constants.NUMBER_TWELFTH_MONTH_YEAR:
                month_end = datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(
                    days=1,
                )
            else:
                month_end = datetime(
                    year,
                    month + 1,
                    1,
                    tzinfo=UTC,
                ) - timedelta(days=1)

            # Доходы за месяц
            month_income = await Income.objects.filter(
                user=user,
                date__range=(month_start, month_end),
            ).aaggregate(total=Sum('amount'))

            # Расходы за месяц
            month_expense = await Expense.objects.filter(
                user=user,
                date__range=(month_start, month_end),
            ).aaggregate(total=Sum('amount'))

            monthly_data.append(
                {
                    'month': month,
                    'income': month_income['total'] or 0,
                    'expense': month_expense['total'] or 0,
                    'net': (month_income['total'] or 0)
                    - (month_expense['total'] or 0),
                },
            )

        # Общая статистика за год
        yearly_income = await Income.objects.filter(
            user=user,
            date__year=year,
        ).aaggregate(
            total=Sum('amount'),
            count=Count('id'),
            avg=Avg('amount'),
        )

        yearly_expense = await Expense.objects.filter(
            user=user,
            date__year=year,
        ).aaggregate(
            total=Sum('amount'),
            count=Count('id'),
            avg=Avg('amount'),
        )

        # Топ категорий за год
        top_income_year_qs = (
            Income.objects.filter(
                user=user,
                date__year=year,
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
            )
            .order_by('-total')[:10]
        )
        top_income_categories: list[dict[str, Any]] = await sync_to_async(
            lambda: list(top_income_year_qs),
        )()  # type: ignore[misc]

        top_expense_year_qs = (
            Expense.objects.filter(
                user=user,
                date__year=year,
            )
            .values('category__name')
            .annotate(
                total=Sum('amount'),
            )
            .order_by('-total')[:10]
        )
        top_expense_categories: list[dict[str, Any]] = await sync_to_async(
            lambda: list(top_expense_year_qs),
        )()  # type: ignore[misc]

        report_data = {
            'year': year,
            'monthly_data': monthly_data,
            'yearly_income': yearly_income,
            'yearly_expense': yearly_expense,
            'top_income_categories': list(top_income_categories),
            'top_expense_categories': list(top_expense_categories),
            'summary': {
                'total_income': yearly_income['total'] or 0,
                'total_expense': yearly_expense['total'] or 0,
                'net_income': (yearly_income['total'] or 0)
                - (yearly_expense['total'] or 0),
                'savings_rate': (
                    (
                        (yearly_income['total'] or 0)
                        - (yearly_expense['total'] or 0)
                    )
                    / (yearly_income['total'] or 1)
                    * 100
                )
                if yearly_income['total']
                else 0,
            },
        }

        logger.info(
            'Yearly report generated successfully',
            user_id=user_id,
            year=year,
            total_income=str(yearly_income['total']),  # type: ignore[index]
            total_expense=str(yearly_expense['total']),  # type: ignore[index]
            net_income=str(report_data['summary']['net_income']),  # type: ignore[index]
            transactions_count=(yearly_income['count'] or 0)  # type: ignore[index]
            + (yearly_expense['count'] or 0),  # type: ignore[index]
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


async def generate_user_statistics(
    user_id: int,
) -> dict[str, Any]:
    """
    Генерация общей статистики пользователя.

    Args:
        user_id: ID пользователя
        context: Контекст задачи

    Returns:
        Общая статистика
    """
    logger.info(
        'Starting user statistics generation',
        user_id=user_id,
    )

    try:
        user = await User.objects.aget(id=user_id)

        # Общая статистика
        total_income = await Income.objects.filter(user=user).aaggregate(
            total=Sum('amount'),
            count=Count('id'),
            avg=Avg('amount'),
        )

        total_expense = await Expense.objects.filter(user=user).aaggregate(
            total=Sum('amount'),
            count=Count('id'),
            avg=Avg('amount'),
        )

        total_receipts = await Receipt.objects.filter(user=user).aaggregate(
            total=Sum('total_sum'),
            count=Count('id'),
            avg=Avg('total_sum'),
        )

        # Статистика по категориям
        income_cat_qs = (
            Income.objects.filter(user=user)
            .values(
                'category__name',
            )
            .annotate(
                total=Sum('amount'),
                count=Count('id'),
            )
            .order_by('-total')[:10]
        )
        income_categories: list[dict[str, Any]] = await sync_to_async(
            lambda: list(income_cat_qs),
        )()  # type: ignore[misc]

        expense_cat_qs = (
            Expense.objects.filter(user=user)
            .values(
                'category__name',
            )
            .annotate(
                total=Sum('amount'),
                count=Count('id'),
            )
            .order_by('-total')[:10]
        )
        expense_categories: list[dict[str, Any]] = await sync_to_async(
            lambda: list(expense_cat_qs),
        )()  # type: ignore[misc]

        # Статистика по времени
        first_income = await Income.objects.filter(user=user).aaggregate(
            first_date=Min('date'),
            last_date=Max('date'),
        )

        first_expense = await Expense.objects.filter(user=user).aaggregate(
            first_date=Min('date'),
            last_date=Max('date'),
        )

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
            'summary': {
                'net_worth': (total_income['total'] or 0)
                - (total_expense['total'] or 0),
                'total_transactions': (total_income['count'] or 0)
                + (total_expense['count'] or 0),
                'avg_transaction': (
                    (
                        (total_income['total'] or 0)
                        + (total_expense['total'] or 0)
                    )
                    / (
                        (total_income['count'] or 0)
                        + (total_expense['count'] or 0)
                    )
                )
                if (
                    (total_income['count'] or 0) + (total_expense['count'] or 0)
                )
                > 0
                else 0,
            },
        }

        logger.info(
            'User statistics generated successfully',
            user_id=user_id,
            total_income=str(total_income['total']),  # type: ignore[index]
            total_expense=str(total_expense['total']),  # type: ignore[index]
            net_worth=str(stats_data['summary']['net_worth']),  # type: ignore[index]
            total_transactions=stats_data['summary']['total_transactions'],  # type: ignore[index]
            receipts_count=total_receipts['count'],  # type: ignore[index]
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
