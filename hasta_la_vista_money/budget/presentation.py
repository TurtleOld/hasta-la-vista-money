"""Presentation helpers for budget HTMX fragments."""

from datetime import date
from decimal import Decimal
from typing import Any

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
) -> dict[str, Any]:
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
                    'percent': percent,
                    'percent_label': _format_percent(percent),
                    'progress_width': min(
                        float(percent or constants.ZERO),
                        constants.ONE_HUNDRED,
                    ),
                    'status': _resolve_status(table_type, percent, fact, plan),
                    'visible_from': max(len(months) - 6, 0),
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
                'percent': percent,
                'percent_label': _format_percent(percent),
                'progress_width': min(
                    float(percent or constants.ZERO),
                    constants.ONE_HUNDRED,
                ),
                'status': _resolve_status(table_type, percent, fact, plan),
                'visible_from': max(len(months) - 6, 0),
            },
        )

    return {
        'budget_table_type': table_type,
        'budget_table_id': f'{table_type}-budget-table',
        'budget_months': months,
        'budget_visible_6': min(len(months), constants.SIX),
        'budget_visible_12': min(len(months), constants.TWELVE),
        'budget_visible_default': min(len(months), constants.SIX),
        'budget_rows': matrix_rows,
        'budget_total_cells': total_cells,
    }


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
