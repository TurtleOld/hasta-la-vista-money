"""Утилиты для работы с датами и периодами.

Модуль предоставляет функции для расчета дат периодов,
используемые в статистике и аналитике.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.utils import timezone


def get_month_start_end(period_date: date | None = None) -> tuple[date, date]:
    """Получить начало и конец месяца для указанной даты.

    Args:
        period_date: Дата для расчета периода. Если None, используется
            текущая дата.

    Returns:
        Кортеж из (начало_месяца, конец_месяца).
    """
    if period_date is None:
        period_date = timezone.now().date()

    month_start = period_date.replace(day=1)
    last_day = (month_start + relativedelta(months=1) - timedelta(days=1)).day
    month_end = month_start.replace(day=last_day)

    return month_start, month_end


def get_last_month_start_end(
    period_date: date | None = None,
) -> tuple[date, date]:
    """Получить начало и конец предыдущего месяца.

    Args:
        period_date: Дата для расчета периода. Если None, используется
            текущая дата.

    Returns:
        Кортеж из (начало_предыдущего_месяца, конец_предыдущего_месяца).
    """
    if period_date is None:
        period_date = timezone.now().date()

    current_month_start = period_date.replace(day=1)
    last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
    last_month_end = current_month_start - timedelta(days=1)

    return last_month_start, last_month_end


def get_period_dates(
    period_type: str = 'month',
    period_date: date | None = None,
) -> dict[str, datetime]:
    """Получить даты начала и конца периода.

    Args:
        period_type: Тип периода ('month', 'quarter', 'year').
            По умолчанию 'month'.
        period_date: Дата для расчета периода. Если None, используется
            текущая дата.

    Returns:
        Словарь с ключами:
        - 'current_start': datetime начала текущего периода
        - 'current_end': datetime конца текущего периода
        - 'previous_start': datetime начала предыдущего периода
        - 'previous_end': datetime конца предыдущего периода
    """
    if period_date is None:
        period_date = timezone.now().date()

    today_dt = timezone.make_aware(
        datetime.combine(period_date, time.max),
    )

    if period_type == 'month':
        current_start = period_date.replace(day=1)
        previous_start = (current_start - timedelta(days=1)).replace(day=1)
        previous_end = current_start - timedelta(days=1)
    elif period_type == 'quarter':
        quarter = (period_date.month - 1) // 3
        current_start = period_date.replace(month=quarter * 3 + 1, day=1)
        previous_start = (current_start - relativedelta(months=3)).replace(
            day=1,
        )
        previous_end = current_start - timedelta(days=1)
    elif period_type == 'year':
        current_start = period_date.replace(month=1, day=1)
        previous_start = (current_start - relativedelta(years=1)).replace(day=1)
        previous_end = current_start - timedelta(days=1)
    else:
        current_start = period_date.replace(day=1)
        previous_start = (current_start - timedelta(days=1)).replace(day=1)
        previous_end = current_start - timedelta(days=1)

    current_start_dt = timezone.make_aware(
        datetime.combine(current_start, time.min),
    )
    previous_start_dt = timezone.make_aware(
        datetime.combine(previous_start, time.min),
    )
    previous_end_dt = timezone.make_aware(
        datetime.combine(previous_end, time.max),
    )

    return {
        'current_start': current_start_dt,
        'current_end': today_dt,
        'previous_start': previous_start_dt,
        'previous_end': previous_end_dt,
    }


def to_decimal(value: float | str | None) -> Decimal:
    """Конвертировать значение в Decimal.

    Args:
        value: Значение для конвертации. Может быть int, float, str или None.

    Returns:
        Decimal: Конвертированное значение. Если value is None, возвращает 0.
    """
    if value is None:
        return Decimal(0)
    return Decimal(str(value))
