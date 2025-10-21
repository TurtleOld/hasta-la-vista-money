from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta
from django.db.models import QuerySet, Sum
from django.utils import timezone

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
from hasta_la_vista_money.finance_account.prepare import (
    collect_info_expense,
    collect_info_income,
    sort_expense_income,
)
from hasta_la_vista_money.finance_account.services import AccountService
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.services.views import collect_info_receipt
from hasta_la_vista_money.users.models import User


def _month_bounds_for_offset(today: date, offset: int) -> tuple[date, date]:
    month_date = today.replace(day=1) - timedelta(days=offset * 30)
    month_start = month_date.replace(day=1)
    if offset == 0:
        month_end = today
    else:
        next_month = month_start + timedelta(days=32)
        month_end = next_month.replace(day=1) - timedelta(days=1)
    return month_start, month_end


def _sum_amount_for_period(
    model,
    user: User,
    start: date,
    end: date,
    date_field: str,
) -> float:
    qs = model.objects.filter(
        user=user,
        **{f'{date_field}__gte': start, f'{date_field}__lte': end},
    )
    return float(qs.aggregate(total=Sum('amount'))['total'] or 0)


def _top_categories_qs(
    model,
    user: User,
    year_start: date,
) -> QuerySet:
    return (
        model.objects.filter(user=user, date__gte=year_start)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:10]
    )


def _dates_amounts(
    dataset: Iterable[dict],
) -> tuple[list[str], list[float]]:
    dates, amounts = [], []
    for item in dataset:
        dates.append(item['date'].strftime('%Y-%m-%d'))
        amounts.append(float(item['total_amount']))
    return dates, amounts


def _build_chart(user: User) -> dict[str, list]:
    exp_ds = (
        Expense.objects.filter(user=user)
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )
    inc_ds = (
        Income.objects.filter(user=user)
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )

    exp_dates, exp_amts = _dates_amounts(exp_ds)
    inc_dates, inc_amts = _dates_amounts(inc_ds)

    all_dates = sorted(set(exp_dates + inc_dates))
    if not all_dates:
        return {'labels': [], 'expense_data': [], 'income_data': []}

    exp_series = [
        exp_amts[exp_dates.index(d)] if d in exp_dates else 0 for d in all_dates
    ]
    inc_series = [
        inc_amts[inc_dates.index(d)] if d in inc_dates else 0 for d in all_dates
    ]

    if len(all_dates) == 1:
        d = date.fromisoformat(all_dates[0])
        dt = datetime.combine(d, time.min)
        aware = timezone.make_aware(dt)
        prev = (aware - timedelta(days=1)).date().isoformat()

        all_dates = [prev, *all_dates]
        exp_series = [0, *exp_series]
        inc_series = [0, *inc_series]

    return {
        'labels': all_dates,
        'expense_data': exp_series,
        'income_data': inc_series,
    }


def _balances_and_delta(
    accounts: QuerySet[Account],
    today: date,
) -> tuple[dict, dict]:
    balances_now = defaultdict(float)
    for acc in accounts:
        balances_now[acc.currency] += float(acc.balance)

    prev_day = today - timedelta(days=1)
    balances_prev = defaultdict(float)
    for acc in accounts:
        if acc.created_at and acc.created_at.date() <= prev_day:
            balances_prev[acc.currency] += float(acc.balance)

    delta = {}
    for cur in balances_now:
        now_val = balances_now.get(cur, 0.0)
        prev_val = balances_prev.get(cur, 0.0)
        diff = now_val - prev_val
        pct = (diff / prev_val * 100) if prev_val else None
        delta[cur] = {'delta': diff, 'percent': pct}

    return dict(balances_now), delta


def _six_months_data(
    user: User,
    today: date,
) -> list[dict[str, float | str]]:
    out = []
    for i in range(6):
        m_start, m_end = _month_bounds_for_offset(today, i)
        exp_sum = _sum_amount_for_period(
            Expense,
            user,
            m_start,
            m_end,
            'date',
        )
        inc_sum = _sum_amount_for_period(
            Income,
            user,
            m_start,
            m_end,
            'date',
        )
        out.append(
            {
                'month': m_start.strftime('%B %Y'),
                'expenses': exp_sum,
                'income': inc_sum,
                'savings': inc_sum - exp_sum,
            }
        )
    out.reverse()
    for m in out:
        m['savings_percent'] = (
            m['savings'] / m['income'] * 100 if m['income'] > 0 else 0
        )
    return out


def _card_months_block(
    card: Account,
    today_month: date,
) -> tuple[list[dict], list[dict]]:
    months: list[dict] = []
    history: list[dict] = []
    now = timezone.now()

    for i in range(12):
        month_date = today_month - relativedelta(months=11 - i)
        purchase_start = month_date.replace(day=1)
        last_day = monthrange(
            purchase_start.year,
            purchase_start.month,
        )[1]
        purchase_end = timezone.make_aware(
            datetime.combine(
                purchase_start.replace(day=last_day),
                time.max,
            ),
        )

        exp_sum = (
            Expense.objects.filter(
                account=card,
                date__range=(purchase_start, purchase_end),
            ).aggregate(total=Sum('amount'))['total']
            or 0
        )
        rcpt_expense = (
            Receipt.objects.filter(
                account=card,
                receipt_date__range=(purchase_start, purchase_end),
                operation_type=RECEIPT_OPERATION_PURCHASE,
            ).aggregate(total=Sum('total_sum'))['total']
            or 0
        )
        rcpt_return = (
            Receipt.objects.filter(
                account=card,
                receipt_date__range=(purchase_start, purchase_end),
                operation_type=RECEIPT_OPERATION_RETURN,
            ).aggregate(total=Sum('total_sum'))['total']
            or 0
        )

        debt = float(exp_sum) + float(rcpt_expense) - float(rcpt_return)

        if getattr(card, 'bank', None) == 'SBERBANK':
            grace_end_date = purchase_start + relativedelta(months=3)
            last_grace_day = monthrange(
                grace_end_date.year,
                grace_end_date.month,
            )[1]
            grace_end = timezone.make_aware(
                datetime.combine(
                    grace_end_date.replace(
                        day=last_grace_day,
                    ),
                    time.max,
                ),
            )
        elif getattr(card, 'bank', None) == 'RAIFFAISENBANK':
            schedule = AccountService.calculate_raiffeisenbank_payment_schedule(
                card,
                purchase_start,
            )
            grace_end = schedule['grace_end_date'] if schedule else purchase_end
        else:
            grace_end = purchase_end

        days_left = (
            (grace_end.date() - now.date()).days if now <= grace_end else 0
        )
        overdue = now > grace_end and debt > 0

        m = {
            'month': purchase_start.strftime('%m.%Y'),
            'purchase_start': purchase_start,
            'purchase_end': purchase_end,
            'grace_end': grace_end,
            'debt_for_month': debt,
            'is_overdue': overdue,
            'days_until_due': days_left,
        }
        months.append(m)

        final_debt = debt
        if getattr(card, 'bank', None) == 'RAIFFAISENBANK' and debt > 0:
            schedule = AccountService.calculate_raiffeisenbank_payment_schedule(
                card,
                purchase_start,
            )
            if schedule:
                final_debt = schedule['final_debt']

        history.append(
            {
                'month': m['month'],
                'debt': debt,
                'final_debt': final_debt,
                'grace_end': grace_end.strftime('%d.%m.%Y'),
                'is_overdue': overdue,
            }
        )

    return months, history


def _apply_payments_to_months(
    months: list[dict],
    payments: list[dict],
) -> None:
    total = sum(float(p['amount']) for p in payments)
    left = total
    for m in months:
        debt = float(m['debt_for_month'])
        if debt <= 0:
            m['payments_made'] = 0
            m['remaining_debt'] = 0
            m['is_paid'] = True
            continue
        paid = min(left, debt)
        m['payments_made'] = paid
        m['remaining_debt'] = max(debt - paid, 0)
        m['is_paid'] = m['remaining_debt'] <= 0
        left = max(left - paid, 0)


def _build_payment_schedule(
    months: list[dict],
    history: list[dict],
    card: Account,
) -> list[dict]:
    schedule: list[dict] = []
    for m in months:
        if m['debt_for_month'] <= 0:
            continue
        due = m['grace_end'].strftime('%d.%m.%Y')
        if getattr(card, 'bank', None) == 'RAIFFAISENBANK':
            for h in history:
                if h['month'] == m['month']:
                    due = h['grace_end']
                    break
        schedule.append(
            {
                'month': m['month'],
                'sum_expense': m['debt_for_month'],
                'payments_made': m['payments_made'],
                'remaining_debt': m['remaining_debt'],
                'payment_due': due,
                'is_overdue': m['is_overdue'],
                'days_until_due': m['days_until_due'],
                'is_paid': m['is_paid'],
            }
        )
    return schedule


def _credit_cards_block(accounts: QuerySet[Account]) -> list[dict]:
    out: list[dict] = []
    today_month = timezone.now().date().replace(day=1)

    credit_cards = accounts.filter(
        type_account__in=[ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_CREDIT]
    )

    for card in credit_cards:
        debt_now = card.get_credit_card_debt()
        months, history = _card_months_block(card, today_month)

        payments = list(
            Income.objects.filter(account=card)
            .order_by('date')
            .values('amount', 'date')
        )
        _apply_payments_to_months(months, payments)
        schedule = _build_payment_schedule(months, history, card)

        current_info = card.calculate_grace_period_info(today_month)
        current_info['debt_for_month'] = max(
            0,
            current_info.get('debt_for_month', 0),
        )
        current_info['final_debt'] = max(
            0,
            current_info.get('final_debt', 0),
        )

        limit_left = (card.limit_credit or 0) - (debt_now or 0)

        out.append(
            {
                'name': card.name_account,
                'limit': card.limit_credit,
                'debt_now': debt_now,
                'current_grace_info': current_info,
                'history': history,
                'currency': card.currency,
                'card_obj': card,
                'limit_left': limit_left,
                'payment_schedule': schedule,
            }
        )
    return out


def get_user_detailed_statistics(user: User) -> dict[str, Any]:
    now = timezone.now()
    today = now.date()

    months_data = _six_months_data(user, today)
    year_start = today.replace(month=1, day=1)
    top_expense_categories = _top_categories_qs(Expense, user, year_start)
    top_income_categories = _top_categories_qs(Income, user, year_start)

    receipt_info_by_month = collect_info_receipt(user=user)

    incomes = collect_info_income(user)
    for it in incomes:
        it['type'] = 'income'

    expenses = collect_info_expense(user)
    for it in expenses:
        it['type'] = 'expense'

    income_expense = sort_expense_income(expenses, incomes)

    transfer_money_log = (
        TransferMoneyLog.objects.filter(user=user)
        .select_related('to_account', 'from_account')
        .order_by('-created_at')[:20]
    )

    accounts = Account.objects.filter(user=user).select_related('user')
    balances_by_currency, delta_by_currency = _balances_and_delta(
        accounts,
        today,
    )

    chart_combined = _build_chart(user)

    credit_cards_data = _credit_cards_block(accounts)

    return {
        'months_data': months_data,
        'top_expense_categories': list(top_expense_categories),
        'top_income_categories': list(top_income_categories),
        'receipt_info_by_month': receipt_info_by_month,
        'income_expense': income_expense,
        'transfer_money_log': transfer_money_log,
        'accounts': accounts,
        'balances_by_currency': dict(balances_by_currency),
        'delta_by_currency': delta_by_currency,
        'chart_combined': chart_combined,
        'user': user,
        'credit_cards_data': credit_cards_data,
    }
