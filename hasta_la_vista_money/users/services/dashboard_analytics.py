"""Сервисы аналитики для дашборда."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
from dateutil.relativedelta import relativedelta
from django.db.models import Sum
from django.utils import timezone

from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


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
    today = timezone.now().date()
    today_dt = timezone.make_aware(datetime.combine(today, time.max))

    if period_type == 'month':
        current_start = today.replace(day=1)
        previous_start = (current_start - timedelta(days=1)).replace(day=1)
        previous_end = current_start - timedelta(days=1)
    elif period_type == 'quarter':
        quarter = (today.month - 1) // 3
        current_start = today.replace(month=quarter * 3 + 1, day=1)
        previous_start = (current_start - relativedelta(months=3)).replace(
            day=1,
        )
        previous_end = current_start - timedelta(days=1)
    elif period_type == 'year':
        current_start = today.replace(month=1, day=1)
        previous_start = (current_start - relativedelta(years=1)).replace(day=1)
        previous_end = current_start - timedelta(days=1)
    else:
        current_start = today.replace(day=1)
        previous_start = (current_start - timedelta(days=1)).replace(day=1)
        previous_end = current_start - timedelta(days=1)

    current_start_dt = timezone.make_aware(
        datetime.combine(current_start, time.min)
    )
    previous_start_dt = timezone.make_aware(
        datetime.combine(previous_start, time.min)
    )
    previous_end_dt = timezone.make_aware(
        datetime.combine(previous_end, time.max)
    )

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

    return {
        'current': {
            'start': current_start.isoformat(),
            'end': today.isoformat(),
            'expenses': float(current_expenses),
            'income': float(current_income),
            'savings': float(current_savings),
        },
        'previous': {
            'start': previous_start.isoformat(),
            'end': previous_end.isoformat(),
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
            period_date = timezone.now().date().replace(day=1)
    else:
        period_date = timezone.now().date().replace(day=1)

    month_start = period_date.replace(day=1)
    last_day = (month_start + relativedelta(months=1) - timedelta(days=1)).day
    month_end = month_start.replace(day=last_day)

    month_start_dt = timezone.make_aware(
        datetime.combine(month_start, time.min)
    )
    month_end_dt = timezone.make_aware(datetime.combine(month_end, time.max))

    if data_type == 'expense':
        model = Expense
        category_model = ExpenseCategory
        category_relation = 'category'
    else:
        model = Income
        category_model = IncomeCategory
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
            .order_by('-total')[:10]
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
            ).order_by('-date')[:20],
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
