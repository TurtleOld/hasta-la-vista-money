from calendar import monthrange
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from dateutil.relativedelta import relativedelta
from dependency_injector.wiring import Provide, inject
from django.core.cache import cache
from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from typing_extensions import TypedDict

from config.containers import CoreContainer
from core.protocols.services import AccountServiceProtocol
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
from hasta_la_vista_money.finance_account.prepare import (
    collect_info_expense,
    collect_info_income,
    sort_expense_income,
)
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.services.views import collect_info_receipt
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.finance_account.services import (
        GracePeriodInfoDict,
    )


class MonthDataDict(TypedDict, total=False):
    """Данные за месяц."""

    month: str
    expenses: float
    income: float
    savings: float
    savings_percent: float
    balance: float


class ChartDataDict(TypedDict):
    """Данные для графика."""

    labels: list[str]
    expense_data: list[float]
    income_data: list[float]


class DeltaByCurrencyDict(TypedDict, total=False):
    """Изменение баланса по валютам."""

    delta: float
    percent: float | None


class CardMonthDict(TypedDict):
    """Данные месяца для кредитной карты."""

    month: str
    purchase_start: datetime
    purchase_end: datetime
    grace_end: datetime
    debt_for_month: float
    is_overdue: bool
    days_until_due: int
    payments_made: float
    remaining_debt: float
    is_paid: bool


class CardHistoryDict(TypedDict):
    """История по месяцам для кредитной карты."""

    month: str
    debt: float
    final_debt: float
    grace_end: str
    is_overdue: bool


class PaymentItemDict(TypedDict):
    """Элемент платежа."""

    amount: Decimal
    date: date


class PaymentScheduleItemDict(TypedDict):
    """Элемент графика платежей."""

    month: str
    sum_expense: float
    payments_made: float
    remaining_debt: float
    payment_due: str
    is_overdue: bool
    days_until_due: int
    is_paid: bool


class CreditCardDataDict(TypedDict, total=False):
    """Данные кредитной карты."""

    name: str
    limit: Decimal | None
    debt_now: Decimal | None
    current_grace_info: 'GracePeriodInfoDict'
    history: list[CardHistoryDict]
    currency: str
    card_obj: Account
    limit_left: Decimal
    payment_schedule: list[PaymentScheduleItemDict]


class IncomeExpenseDict(TypedDict):
    """Данные о доходе/расходе."""

    id: int
    date: date
    account__name_account: str
    category__name: str
    amount: Decimal
    type: str


class UserDetailedStatisticsDict(TypedDict):
    """Подробная статистика пользователя."""

    months_data: list[MonthDataDict]
    top_expense_categories: list[dict[str, Any]]
    top_income_categories: list[dict[str, Any]]
    receipt_info_by_month: QuerySet[Receipt]
    income_expense: list[IncomeExpenseDict]
    transfer_money_log: QuerySet[TransferMoneyLog]
    accounts: QuerySet[Account]
    balances_by_currency: dict[str, float]
    delta_by_currency: dict[str, DeltaByCurrencyDict]
    chart_combined: ChartDataDict
    user: User
    credit_cards_data: list[CreditCardDataDict]


def _month_bounds_for_offset(today: date, offset: int) -> tuple[date, date]:
    month_date = today.replace(day=1) - timedelta(
        days=offset * constants.DAYS_IN_MONTH_APPROXIMATE,
    )
    month_start = month_date.replace(day=1)
    if offset == 0:
        month_end = today
    else:
        next_month = month_start + timedelta(
            days=constants.DAYS_FOR_NEXT_MONTH_CALC,
        )
        month_end = next_month.replace(day=1) - timedelta(days=1)
    return month_start, month_end


def _sum_amount_for_period(
    model: type[Expense] | type[Income],
    user: User,
    start: date,
    end: date,
    date_field: str,
) -> float:
    start_dt = timezone.make_aware(datetime.combine(start, time.min))
    end_dt = timezone.make_aware(datetime.combine(end, time.max))

    qs = model.objects.filter(
        user=user,
        **{f'{date_field}__gte': start_dt, f'{date_field}__lte': end_dt},
    )
    return float(qs.aggregate(total=Sum('amount'))['total'] or 0)


def _top_categories_qs(
    model: type[Expense] | type[Income],
    user: User,
    year_start: date,
) -> Any:
    year_start_dt = timezone.make_aware(datetime.combine(year_start, time.min))
    return (
        model.objects.filter(user=user, date__gte=year_start_dt)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[: constants.TOP_CATEGORIES_LIMIT]
    )


def _dates_amounts(
    dataset: Iterable[dict[str, Any]],
) -> tuple[list[str], list[float]]:
    dates, amounts = [], []
    for item in dataset:
        dates.append(item['date'].strftime('%Y-%m-%d'))
        amounts.append(float(item['total_amount']))
    return dates, amounts


def _build_chart(user: User) -> ChartDataDict:
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
        exp_amts[exp_dates.index(d)] if d in exp_dates else constants.ZERO
        for d in all_dates
    ]
    inc_series = [
        inc_amts[inc_dates.index(d)] if d in inc_dates else constants.ZERO
        for d in all_dates
    ]

    if len(all_dates) == constants.ONE:
        d = date.fromisoformat(all_dates[0])
        dt = datetime.combine(d, time.min)
        aware = timezone.make_aware(dt)
        prev = (aware - timedelta(days=constants.ONE)).date().isoformat()

        all_dates = [prev, *all_dates]
        exp_series = [constants.ZERO, *exp_series]
        inc_series = [constants.ZERO, *inc_series]

    return {
        'labels': all_dates,
        'expense_data': exp_series,
        'income_data': inc_series,
    }


def _balances_and_delta(
    accounts: QuerySet[Account],
    today: date,
) -> tuple[dict[str, float], dict[str, DeltaByCurrencyDict]]:
    balances_now: dict[str, float] = defaultdict(float)
    for acc in accounts:
        balances_now[acc.currency] += float(acc.balance)

    prev_day = today - timedelta(days=1)
    balances_prev: dict[str, float] = defaultdict(float)
    for acc in accounts:
        if acc.created_at and acc.created_at.date() <= prev_day:
            balances_prev[acc.currency] += float(acc.balance)

    delta = {}
    for cur in balances_now:
        now_val = balances_now.get(cur, 0.0)
        prev_val = balances_prev.get(cur, 0.0)
        diff = now_val - prev_val
        pct = (
            (diff / prev_val * constants.PERCENTAGE_MULTIPLIER)
            if prev_val
            else None
        )
        delta[cur] = {'delta': diff, 'percent': pct}

    return dict(balances_now), delta  # type: ignore[return-value]


def _six_months_data(
    user: User,
    today: date,
) -> list[MonthDataDict]:
    out = []

    for i in range(constants.STATISTICS_MONTHS_COUNT):
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
                'month_start': m_start,
                'month_end': m_end,
            },
        )
    out.reverse()

    if out:
        first_month_start = out[0]['month_start']
        if isinstance(first_month_start, datetime):
            first_month_start_date = first_month_start.date()
        else:
            first_month_start_date = first_month_start  # type: ignore[assignment]
        period_end_date: date = first_month_start_date - timedelta(days=1)

        total_income_before = _sum_amount_for_period(
            Income,
            user,
            date(2000, 1, 1),
            period_end_date,
            'date',
        )
        total_expense_before = _sum_amount_for_period(
            Expense,
            user,
            date(2000, 1, 1),
            period_end_date,
            'date',
        )

        running_balance = total_income_before - total_expense_before
    else:
        running_balance = 0.0

    for m in out:
        income_raw = m.get('income', 0.0) or 0.0
        expenses_raw = m.get('expenses', 0.0) or 0.0
        savings_raw = m.get('savings', 0.0) or 0.0
        income_val = (
            float(income_raw)
            if isinstance(income_raw, int | float | str)
            else 0.0
        )
        expenses_val = (
            float(expenses_raw)
            if isinstance(expenses_raw, int | float | str)
            else 0.0
        )
        savings_val = (
            float(savings_raw)
            if isinstance(savings_raw, int | float | str)
            else 0.0
        )
        m['savings_percent'] = (
            savings_val / income_val * constants.PERCENTAGE_MULTIPLIER
            if income_val > constants.ZERO
            else float(constants.ZERO)
        )

        running_balance = running_balance + income_val - expenses_val

        m['balance'] = round(running_balance, 2)
        del m['month_start']
        del m['month_end']
    return out  # type: ignore[return-value]


@inject
def _card_months_block(
    card: Account,
    today_month: date,
    account_service: AccountServiceProtocol = Provide[
        CoreContainer.account_service
    ],
) -> tuple[list[CardMonthDict], list[CardHistoryDict]]:
    months: list[CardMonthDict] = []
    history: list[CardHistoryDict] = []
    now = timezone.now()

    first_month_date = today_month - relativedelta(
        months=constants.STATISTICS_YEAR_MONTHS_COUNT - constants.ONE,
    )
    first_month_start = timezone.make_aware(
        datetime.combine(first_month_date.replace(day=1), time.min),
    )
    last_month_date = today_month
    last_day = monthrange(last_month_date.year, last_month_date.month)[1]
    last_month_end = timezone.make_aware(
        datetime.combine(
            last_month_date.replace(day=last_day),
            time.max,
        ),
    )

    expenses_by_month = (
        Expense.objects.filter(
            account=card,
            date__gte=first_month_start,
            date__lte=last_month_end,
        )
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total=Sum('amount'))
    )

    receipts_by_month = (
        Receipt.objects.filter(
            account=card,
            receipt_date__gte=first_month_start,
            receipt_date__lte=last_month_end,
        )
        .annotate(month=TruncMonth('receipt_date'))
        .values('month', 'operation_type')
        .annotate(total=Sum('total_sum'))
    )

    expenses_dict: dict[date, Decimal] = {}
    for item in expenses_by_month:
        month_date = item['month'].date().replace(day=1)
        expenses_dict[month_date] = Decimal(str(item['total'] or 0))

    receipts_dict: dict[date, dict[int, Decimal]] = defaultdict(
        lambda: defaultdict(lambda: Decimal(0)),
    )
    for item in receipts_by_month:
        month_date = item['month'].date().replace(day=1)
        operation_type = item['operation_type']
        receipts_dict[month_date][operation_type] = Decimal(
            str(item['total'] or 0),
        )

    for i in range(constants.STATISTICS_YEAR_MONTHS_COUNT):
        month_date = today_month - relativedelta(
            months=constants.STATISTICS_YEAR_MONTHS_COUNT - constants.ONE - i,
        )
        purchase_start_date = month_date.replace(day=1)
        last_day = monthrange(
            purchase_start_date.year,
            purchase_start_date.month,
        )[1]
        purchase_start = timezone.make_aware(
            datetime.combine(purchase_start_date, time.min),
        )
        purchase_end = timezone.make_aware(
            datetime.combine(
                purchase_start_date.replace(day=last_day),
                time.max,
            ),
        )

        exp_sum = expenses_dict.get(purchase_start_date, Decimal(0))
        rcpt_expense = receipts_dict[purchase_start_date].get(
            RECEIPT_OPERATION_PURCHASE,
            Decimal(0),
        )
        rcpt_return = receipts_dict[purchase_start_date].get(
            RECEIPT_OPERATION_RETURN,
            Decimal(0),
        )

        debt = float(exp_sum) + float(rcpt_expense) - float(rcpt_return)

        if getattr(card, 'bank', None) == 'SBERBANK':
            grace_end_date = purchase_start_date + relativedelta(
                months=constants.GRACE_PERIOD_MONTHS_SBERBANK,
            )
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
            schedule = (
                account_service.calculate_raiffeisenbank_payment_schedule(
                    card,
                    purchase_start_date,
                )
            )
            grace_end = schedule['grace_end_date'] if schedule else purchase_end
        else:
            grace_end = purchase_end

        days_left = (
            (grace_end.date() - now.date()).days
            if now <= grace_end
            else constants.ZERO
        )
        overdue = now > grace_end and debt > constants.ZERO

        m: CardMonthDict = {
            'month': purchase_start_date.strftime('%m.%Y'),
            'purchase_start': purchase_start,
            'purchase_end': purchase_end,
            'grace_end': grace_end,
            'debt_for_month': debt,
            'is_overdue': overdue,
            'days_until_due': days_left,
            'payments_made': 0.0,
            'remaining_debt': 0.0,
            'is_paid': False,
        }
        months.append(m)

        final_debt = debt
        if (
            getattr(card, 'bank', None) == 'RAIFFAISENBANK'
            and debt > constants.ZERO
        ):
            schedule = (
                account_service.calculate_raiffeisenbank_payment_schedule(
                    card,
                    purchase_start,
                )
            )
            if schedule:
                final_debt = float(schedule['final_debt'])

        history.append(
            {
                'month': str(m['month']),
                'debt': debt,
                'final_debt': final_debt,
                'grace_end': grace_end.strftime('%d.%m.%Y'),
                'is_overdue': overdue,
            },
        )

    return months, history


def _apply_payments_to_months(
    months: list[CardMonthDict],
    payments: list[PaymentItemDict],
) -> None:
    total = sum(float(p['amount']) for p in payments)
    left = total
    for m in months:
        debt = float(m['debt_for_month'])
        if debt <= constants.ZERO:
            m['payments_made'] = constants.ZERO
            m['remaining_debt'] = constants.ZERO
            m['is_paid'] = True
            continue
        paid = min(left, debt)
        m['payments_made'] = paid
        m['remaining_debt'] = max(debt - paid, constants.ZERO)
        m['is_paid'] = m['remaining_debt'] <= constants.ZERO
        left = max(left - paid, constants.ZERO)


def _build_payment_schedule(
    months: list[CardMonthDict],
    history: list[CardHistoryDict],
    card: Account,
) -> list[PaymentScheduleItemDict]:
    schedule: list[PaymentScheduleItemDict] = []
    for m in months:
        if m['debt_for_month'] <= constants.ZERO:
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
            },
        )
    return schedule


@inject
def _credit_cards_block(
    accounts: QuerySet[Account],
    account_service: AccountServiceProtocol = Provide[
        CoreContainer.account_service
    ],
) -> list[CreditCardDataDict]:
    out: list[CreditCardDataDict] = []
    today_month = timezone.now().date().replace(day=1)

    credit_cards = accounts.filter(
        type_account__in=[ACCOUNT_TYPE_CREDIT_CARD, ACCOUNT_TYPE_CREDIT],
    )

    for card in credit_cards:
        debt_now = account_service.get_credit_card_debt(card)
        months, history = _card_months_block(card, today_month)

        payments_raw = list(
            Income.objects.filter(account=card)
            .order_by('date')
            .values('amount', 'date'),
        )
        payments: list[PaymentItemDict] = [
            {'amount': Decimal(str(p['amount'])), 'date': p['date']}
            for p in payments_raw
        ]
        _apply_payments_to_months(months, payments)
        schedule = _build_payment_schedule(months, history, card)

        current_info = account_service.calculate_grace_period_info(
            card,
            today_month,
        )
        current_info['debt_for_month'] = Decimal(
            str(
                max(
                    0,
                    current_info.get('debt_for_month', 0),
                ),
            ),
        )
        current_info['final_debt'] = Decimal(
            str(
                max(
                    0,
                    current_info.get('final_debt', 0),
                ),
            ),
        )

        limit_left = Decimal(str((card.limit_credit or 0) - (debt_now or 0)))

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
            },
        )
    return out


def get_user_detailed_statistics(user: User) -> UserDetailedStatisticsDict:
    """
    Получение детальной статистики пользователя с кешированием.

    Args:
        user: Пользователь для которого собирается статистика

    Returns:
        Словарь с детальной статистикой пользователя
    """
    cache_key = f'user_stats_{user.pk}'
    cached_stats = cache.get(cache_key)

    if cached_stats is not None:
        return cached_stats  # type: ignore[no-any-return]

    now = timezone.now()
    today = now.date()

    months_data = _six_months_data(user, today)
    year_start = today.replace(month=1, day=1)
    top_expense_categories = _top_categories_qs(Expense, user, year_start)
    top_income_categories = _top_categories_qs(Income, user, year_start)

    receipt_info_by_month = collect_info_receipt(user=user)

    incomes = collect_info_income(user)
    for it in incomes:
        it['type'] = 'income'  # type: ignore[typeddict-unknown-key]

    expenses = collect_info_expense(user)
    for it in expenses:
        it['type'] = 'expense'  # type: ignore[typeddict-unknown-key]

    income_expense = sort_expense_income(expenses, incomes)

    transfer_money_log = (
        TransferMoneyLog.objects.filter(user=user)
        .select_related('to_account', 'from_account', 'user')
        .order_by('-created_at')[: constants.TRANSFER_LOG_LIMIT]
    )

    accounts = Account.objects.filter(user=user).select_related('user')
    balances_by_currency, delta_by_currency = _balances_and_delta(
        accounts,
        today,
    )

    chart_combined = _build_chart(user)

    credit_cards_data = _credit_cards_block(accounts)

    stats = {
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

    cache.set(cache_key, stats, 600)

    return stats  # type: ignore[return-value]
