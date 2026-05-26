"""Presentation helpers for budget HTMX fragments."""

from datetime import date
from decimal import Decimal
from typing import Any

from django.utils import timezone

from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.services.budget import (
    ExpenseDataRowDict,
    IncomeDataRowDict,
)


def build_budget_matrix_context(
    table_type: str,
    months: list[date],
    rows: list[ExpenseDataRowDict] | list[IncomeDataRowDict],
    total_fact: list[int] | list[Decimal],
    total_plan: list[int] | list[Decimal],
    current_date: date | None = None,
    selected_range: str = '6',
) -> dict[str, Any]:
    visible_range = _normalize_visible_range(selected_range)
    visible_start, visible_count = _visible_state(
        months,
        current_date,
        visible_range,
    )
    month_columns = []
    for index, month in enumerate(months):
        month_columns.append(
            {
                'month': month,
                'index': index,
                'is_visible_default': _is_visible_month(
                    index,
                    visible_start,
                    visible_count,
                ),
            },
        )

    matrix_rows = []
    for row in rows:
        cells = []
        for index, month in enumerate(months):
            fact = Decimal(str(row['fact'][index]))
            plan = Decimal(str(row['plan'][index]))
            percent = row['percent'][index]
            cells.append(
                {
                    'month': month,
                    'fact': fact,
                    'plan': plan,
                    'diff': Decimal(str(row['diff'][index])),
                    'index': index,
                    'percent': percent,
                    'percent_label': _format_percent(percent),
                    'progress_width': min(
                        float(percent or constants.ZERO),
                        constants.ONE_HUNDRED,
                    ),
                    'status': _resolve_status(table_type, percent, fact, plan),
                    'visible_from': visible_start,
                    'is_visible_default': _is_visible_month(
                        index,
                        visible_start,
                        visible_count,
                    ),
                },
            )
        matrix_rows.append(
            {
                'category': row['category'],
                'category_id': row['category_id'],
                'cells': cells,
            },
        )

    total_cells = []
    for index, month in enumerate(months):
        fact = Decimal(str(total_fact[index]))
        plan = Decimal(str(total_plan[index]))
        percent = (
            float(fact / plan * Decimal(constants.ONE_HUNDRED))
            if plan
            else None
        )
        total_cells.append(
            {
                'month': month,
                'fact': fact,
                'plan': plan,
                'diff': fact - plan,
                'index': index,
                'percent': percent,
                'percent_label': _format_percent(percent),
                'progress_width': min(
                    float(percent or constants.ZERO),
                    constants.ONE_HUNDRED,
                ),
                'status': _resolve_status(table_type, percent, fact, plan),
                'visible_from': visible_start,
                'is_visible_default': _is_visible_month(
                    index,
                    visible_start,
                    visible_count,
                ),
            },
        )

    return {
        'budget_table_type': table_type,
        'budget_table_id': f'{table_type}-budget-table',
        'budget_table_url_name': f'budget:{table_type}_table',
        'budget_months': months,
        'budget_month_columns': month_columns,
        'budget_visible_6': min(len(months), constants.SIX),
        'budget_visible_12': min(len(months), constants.TWELVE),
        'budget_visible_default': visible_count,
        'budget_visible_range': visible_range,
        'budget_visible_start': visible_start,
        'budget_rows': matrix_rows,
        'budget_total_cells': total_cells,
    }


def _normalize_visible_range(selected_range: str) -> str:
    if selected_range in {'6', '12', 'all'}:
        return selected_range
    return '6'


def _visible_state(
    months: list[date],
    current_date: date | None,
    visible_range: str,
) -> tuple[int, int]:
    if visible_range == 'all':
        return constants.ZERO, len(months)

    visible_start = _default_visible_start(months, current_date)
    visible_count = constants.TWELVE if visible_range == '12' else constants.SIX
    return visible_start, min(len(months), visible_count)


def _default_visible_start(
    months: list[date],
    current_date: date | None,
) -> int:
    if not months:
        return constants.ZERO

    target_date = current_date or timezone.localdate()
    current_month = target_date.replace(day=1)
    for index, month in enumerate(months):
        if month >= current_month:
            return index
    return max(len(months) - constants.SIX, constants.ZERO)


def _is_visible_month(
    index: int,
    visible_start: int,
    visible_count: int,
) -> bool:
    return visible_start <= index < visible_start + visible_count


def _resolve_status(
    table_type: str,
    percent: float | None,
    fact: Decimal,
    plan: Decimal,
) -> str:
    if not plan:
        return 'empty'
    if table_type == 'expense':
        status = 'ok'
        if fact > plan:
            status = 'over'
        elif percent is not None and percent >= constants.EIGHTY:
            status = 'warning'
        return status

    status = 'under'
    if fact >= plan:
        status = 'ok'
    elif percent is not None and percent >= constants.EIGHTY:
        status = 'warning'
    return status


def _format_percent(percent: float | None) -> str:
    if percent is None:
        return '—'
    return f'{percent:.0f}%'
