"""Сервисы аналитики для дашборда."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast

import numpy as np
from django.db.models import Sum
from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.utils.date_utils import (
    get_month_start_end,
    get_period_dates,
)


def calculate_linear_trend(
    dates: list[date],
    values: list[Decimal],
) -> dict[str, Any]:
    """
    Рассчитывает линейную регрессию и прогноз.

    Args:
        dates: Список дат
        values: Список значений для каждой даты

    Returns:
        Словарь с коэффициентами тренда, линией тренда и прогнозом
    """
    min_data_points_for_trend = 2
    if len(dates) < min_data_points_for_trend:
        return {
            'error': 'Недостаточно данных для расчёта тренда',
            'slope': 0.0,
            'intercept': 0.0,
            'r_squared': 0.0,
            'trend_line': [],
            'forecast': [],
        }

    # Преобразуем даты в числа (дни от начала)
    days = np.array([(d - dates[0]).days for d in dates])
    amounts = np.array([float(v) for v in values])

    # Линейная регрессия: y = mx + b
    coeffs = np.polyfit(days, amounts, 1)
    slope, intercept = coeffs

    fitted = np.polyval(coeffs, days)
    ss_res = np.sum((amounts - fitted) ** 2)
    ss_tot = np.sum((amounts - np.mean(amounts)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    trend_line = [
        {'date': dates[i].isoformat(), 'value': float(fitted[i])}
        for i in range(len(dates))
    ]

    # Прогноз на 30 дней вперёд
    last_day = days[-1]
    forecast_days = np.arange(last_day + 1, last_day + 31)
    forecast_values = np.polyval(coeffs, forecast_days)
    forecast = [
        {
            'date': (dates[-1] + timedelta(days=int(d - last_day))).isoformat(),
            'value': float(forecast_values[i]),
        }
        for i, d in enumerate(forecast_days)
    ]

    return {
        'slope': float(slope),
        'intercept': float(intercept),
        'r_squared': float(r_squared),
        'trend_line': trend_line,
        'forecast': forecast,
    }


def get_period_comparison(
    user: User,
    period_type: str,
) -> dict[str, Any]:
    """
    Сравнение текущего и прошлого периода.

    Args:
        user: Пользователь
        period_type: Тип периода ('month', 'quarter', 'year')

    Returns:
        Словарь с данными текущего и прошлого периода
    """
    period_dates = get_period_dates(period_type=period_type)
    current_start_dt = period_dates['current_start']
    today_dt = period_dates['current_end']
    previous_start_dt = period_dates['previous_start']
    previous_end_dt = period_dates['previous_end']

    current_expenses = Expense.objects.filter(
        user=user,
        date__gte=current_start_dt,
        date__lte=today_dt,
    ).aggregate(total=Sum('amount'))['total'] or Decimal(0)

    previous_expenses = Expense.objects.filter(
        user=user,
        date__gte=previous_start_dt,
        date__lte=previous_end_dt,
    ).aggregate(total=Sum('amount'))['total'] or Decimal(0)

    current_income = Income.objects.filter(
        user=user,
        date__gte=current_start_dt,
        date__lte=today_dt,
    ).aggregate(total=Sum('amount'))['total'] or Decimal(0)

    previous_income = Income.objects.filter(
        user=user,
        date__gte=previous_start_dt,
        date__lte=previous_end_dt,
    ).aggregate(total=Sum('amount'))['total'] or Decimal(0)

    expenses_change_percent = (
        float((current_expenses - previous_expenses) / previous_expenses * 100)
        if previous_expenses > 0
        else 0.0
    )

    income_change_percent = (
        float((current_income - previous_income) / previous_income * 100)
        if previous_income > 0
        else 0.0
    )

    previous_savings = previous_income - previous_expenses
    current_savings = current_income - current_expenses
    savings_change_percent = (
        float((current_savings - previous_savings) / previous_savings * 100)
        if previous_savings > 0
        else 0.0
    )

    today = timezone.now().date()

    return {
        'current': {
            'start': period_dates['current_start'].date().isoformat(),
            'end': today.isoformat(),
            'expenses': float(current_expenses),
            'income': float(current_income),
            'savings': float(current_savings),
        },
        'previous': {
            'start': period_dates['previous_start'].date().isoformat(),
            'end': period_dates['previous_end'].date().isoformat(),
            'expenses': float(previous_expenses),
            'income': float(previous_income),
            'savings': float(previous_savings),
        },
        'change_percent': {
            'expenses': expenses_change_percent,
            'income': income_change_percent,
            'savings': savings_change_percent,
        },
    }


def get_drill_down_data(
    user: User,
    category_id: str | None,
    date_str: str | None,
    data_type: str = 'expense',
) -> dict[str, Any]:
    """
    Получение детализации по категориям (drill-down).

    Args:
        user: Пользователь
        category_id: ID категории (если None, возвращает топ категории)
        date_str: Дата в формате YYYY-MM (если None, текущий месяц)
        data_type: Тип данных ('expense' или 'income')

    Returns:
        Словарь с данными для drill-down графика
    """
    if date_str:
        try:
            period_date = date.fromisoformat(date_str + '-01')
        except ValueError:
            period_date = timezone.now().date()
    else:
        period_date = timezone.now().date()

    month_start, month_end = get_month_start_end(period_date)

    month_start_dt = timezone.make_aware(
        datetime.combine(month_start, time.min),
    )
    month_end_dt = timezone.make_aware(datetime.combine(month_end, time.max))

    if data_type == 'expense':
        model: type[Expense | Income] = Expense
        category_model: type[ExpenseCategory | IncomeCategory] = ExpenseCategory
        category_relation = 'category'
    else:
        model = cast('type[Expense | Income]', Income)
        category_model = cast(
            'type[ExpenseCategory | IncomeCategory]', IncomeCategory
        )
        category_relation = 'category'

    if category_id is None:
        top_categories = (
            model.objects.filter(
                user=user,
                date__gte=month_start_dt,
                date__lte=month_end_dt,
                **{f'{category_relation}__parent_category__isnull': True},
            )
            .values(
                f'{category_relation}__id',
                f'{category_relation}__name',
            )
            .annotate(total=Sum('amount'))
            .order_by('-total')[: constants.TOP_CATEGORIES_LIMIT]
        )

        data = [
            {
                'name': cat[f'{category_relation}__name'],
                'value': float(cat['total']),
                'category_id': cat[f'{category_relation}__id'],
            }
            for cat in top_categories
        ]

        return {
            'period': date_str or month_start.strftime('%Y-%m'),
            'data': data,
            'level': 0,
        }

    category = category_model.objects.filter(
        user=user,
        id=category_id,
    ).first()

    if not category:
        return {'error': 'Категория не найдена', 'data': []}

    subcategories = (
        model.objects.filter(
            user=user,
            date__gte=month_start_dt,
            date__lte=month_end_dt,
            **{f'{category_relation}__parent_category_id': category_id},
        )
        .values(
            f'{category_relation}__id',
            f'{category_relation}__name',
        )
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )

    data = [
        {
            'name': subcat[f'{category_relation}__name'],
            'value': float(subcat['total']),
            'category_id': subcat[f'{category_relation}__id'],
        }
        for subcat in subcategories
    ]

    if not data:
        transactions = list(
            model.objects.filter(
                user=user,
                date__gte=month_start_dt,
                date__lte=month_end_dt,
                **{f'{category_relation}__id': category_id},
            ).order_by('-date')[: constants.RECENT_RECEIPTS_LIMIT],
        )

        data = [
            {
                'name': trans.date.strftime('%d.%m.%Y'),
                'value': float(trans.amount),
                'transaction_id': trans.pk,
            }
            for trans in transactions
        ]

    return {
        'period': date_str or month_start.strftime('%Y-%m'),
        'category_id': category_id,
        'category_name': category.name,
        'data': data,
        'level': 1,
    }
