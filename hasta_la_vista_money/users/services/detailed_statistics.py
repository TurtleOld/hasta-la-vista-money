from typing import Any, Dict
from collections import defaultdict
from datetime import datetime, timedelta, time
from calendar import monthrange
from dateutil.relativedelta import relativedelta
from django.db.models import Sum
from django.utils import timezone
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.finance_account.models import Account, TransferMoneyLog
from hasta_la_vista_money.finance_account.services import AccountService
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.services.views import collect_info_receipt
from hasta_la_vista_money.finance_account.prepare import (
    collect_info_expense,
    collect_info_income,
    sort_expense_income,
)


def get_user_detailed_statistics(user: User) -> Dict[str, Any]:
    today = timezone.now().date()
    months_data = []
    for i in range(6):
        month_date = today.replace(day=1) - timedelta(days=i * 30)
        month_start = month_date.replace(day=1)
        if i == 0:
            month_end = today
        else:
            next_month = month_start + timedelta(days=32)
            month_end = next_month.replace(day=1) - timedelta(days=1)
        month_expenses = (
            Expense.objects.filter(
                user=user,
                date__gte=month_start,
                date__lte=month_end,
            ).aggregate(total=Sum('amount'))['total']
            or 0
        )
        month_income = (
            Income.objects.filter(
                user=user,
                date__gte=month_start,
                date__lte=month_end,
            ).aggregate(total=Sum('amount'))['total']
            or 0
        )
        months_data.append(
            {
                'month': month_start.strftime('%B %Y'),
                'expenses': float(month_expenses),
                'income': float(month_income),
                'savings': float(month_income - month_expenses),
            }
        )
    months_data.reverse()
    for month_data in months_data:
        if month_data['income'] > 0:
            month_data['savings_percent'] = (
                month_data['savings'] / month_data['income']
            ) * 100
        else:
            month_data['savings_percent'] = 0
    year_start = today.replace(month=1, day=1)
    top_expense_categories = (
        Expense.objects.filter(user=user, date__gte=year_start)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:10]
    )
    top_income_categories = (
        Income.objects.filter(user=user, date__gte=year_start)
        .values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:10]
    )
    receipt_info_by_month = collect_info_receipt(user=user)
    incomes = collect_info_income(user)
    for income in incomes:
        income['type'] = 'income'
    expenses = collect_info_expense(user)
    for expense in expenses:
        expense['type'] = 'expense'
    income_expense = sort_expense_income(expenses, incomes)
    transfer_money_log = (
        TransferMoneyLog.objects.filter(user=user)
        .select_related('to_account', 'from_account')
        .order_by('-created_at')[:20]
    )
    accounts = Account.objects.filter(user=user).select_related('user').all()
    balances_by_currency = defaultdict(float)
    for acc in accounts:
        balances_by_currency[acc.currency] += float(acc.balance)
    prev_day = today - timedelta(days=1)
    balances_prev_by_currency = defaultdict(float)
    for acc in accounts:
        if acc.created_at and acc.created_at.date() <= prev_day:
            balances_prev_by_currency[acc.currency] += float(acc.balance)
    delta_by_currency = {}
    for cur in balances_by_currency.keys():
        now = balances_by_currency.get(cur, 0)
        prev = balances_prev_by_currency.get(cur, 0)
        delta = now - prev
        percent = (delta / prev * 100) if prev else None
        delta_by_currency[cur] = {'delta': delta, 'percent': percent}
    expense_dataset = (
        Expense.objects.filter(user=user)
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )
    income_dataset = (
        Income.objects.filter(user=user)
        .values('date')
        .annotate(total_amount=Sum('amount'))
        .order_by('date')
    )

    def transform_data(dataset):
        dates = []
        amounts = []
        for date_amount in dataset:
            dates.append(date_amount['date'].strftime('%Y-%m-%d'))
            amounts.append(float(date_amount['total_amount']))
        return dates, amounts

    expense_dates, expense_amounts = transform_data(expense_dataset)
    income_dates, income_amounts = transform_data(income_dataset)
    all_dates = sorted(set(expense_dates + income_dates))
    if not all_dates:
        chart_combined = {
            'labels': [],
            'expense_data': [],
            'income_data': [],
        }
    else:
        expense_series_data = [
            expense_amounts[expense_dates.index(date)] if date in expense_dates else 0
            for date in all_dates
        ]
        income_series_data = [
            income_amounts[income_dates.index(date)] if date in income_dates else 0
            for date in all_dates
        ]
        if len(all_dates) == 1:
            single_date = datetime.strptime(all_dates[0], '%Y-%m-%d')
            prev_date = (single_date - timedelta(days=1)).strftime('%Y-%m-%d')
            all_dates = [prev_date] + all_dates
            expense_series_data = [0] + expense_series_data
            income_series_data = [0] + income_series_data
        chart_combined = {
            'labels': all_dates,
            'expense_data': expense_series_data,
            'income_data': income_series_data,
        }
    credit_cards = accounts.filter(type_account__in=['CreditCard', 'Credit'])
    credit_cards_data = []
    for card in credit_cards:
        debt_now = card.get_credit_card_debt()
        history = []
        payment_schedule = []
        today_month = timezone.now().date().replace(day=1)
        months = []
        months_map = {}
        for i in range(12):
            month_date = today_month - relativedelta(months=11 - i)
            purchase_start = month_date.replace(day=1)
            last_day = monthrange(purchase_start.year, purchase_start.month)[1]
            purchase_end = datetime.combine(
                purchase_start.replace(day=last_day),
                time.max,
            )
            expense_sum = (
                Expense.objects.filter(
                    account=card,
                    date__range=(purchase_start, purchase_end),
                ).aggregate(total=Sum('amount'))['total']
                or 0
            )
            receipt_expense = (
                Receipt.objects.filter(
                    account=card,
                    receipt_date__range=(purchase_start, purchase_end),
                    operation_type=1,
                ).aggregate(total=Sum('total_sum'))['total']
                or 0
            )
            receipt_return = (
                Receipt.objects.filter(
                    account=card,
                    receipt_date__range=(purchase_start, purchase_end),
                    operation_type=2,
                ).aggregate(total=Sum('total_sum'))['total']
                or 0
            )
            debt_for_month = (
                float(expense_sum) + float(receipt_expense) - float(receipt_return)
            )
            # Банко-зависимый расчёт льготного периода.
            # Для Сбербанка: 1 месяц на покупки + 3 месяца на погашение (текущая доменная логика).
            # Для Райффайзенбанка: 110 дней с первой покупки.
            # Для остальных банков пока заглушка: срок погашения — конец месяца покупок.
            if getattr(card, 'bank', None) == 'SBERBANK':
                grace_end_date = purchase_start + relativedelta(months=3)
                last_day_grace = monthrange(grace_end_date.year, grace_end_date.month)[
                    1
                ]
                grace_end = datetime.combine(
                    grace_end_date.replace(day=last_day_grace),
                    time.max,
                )
            elif getattr(card, 'bank', None) == 'RAIFFAISENBANK':
                # Для Райффайзенбанка используем специальную логику
                raiffeisen_schedule = (
                    AccountService.calculate_raiffeisenbank_payment_schedule(
                        card, purchase_start
                    )
                )
                if raiffeisen_schedule:
                    grace_end = raiffeisen_schedule['grace_end_date']
                else:
                    grace_end = purchase_end
            else:
                grace_end = purchase_end
            days_until_due = (
                (grace_end.date() - timezone.now().date()).days
                if timezone.now() <= grace_end
                else 0
            )
            is_overdue = timezone.now() > grace_end and debt_for_month > 0
            months.append(
                {
                    'month': purchase_start.strftime('%m.%Y'),
                    'purchase_start': purchase_start,
                    'purchase_end': purchase_end,
                    'grace_end': grace_end,
                    'debt_for_month': debt_for_month,
                    'is_overdue': is_overdue,
                    'days_until_due': days_until_due,
                }
            )
            months_map[purchase_start.strftime('%m.%Y')] = months[-1]
            # Для Райффайзенбанка рассчитываем итоговый долг с учётом минимальных платежей
            final_debt = debt_for_month
            if getattr(card, 'bank', None) == 'RAIFFAISENBANK' and debt_for_month > 0:
                raiffeisen_schedule = (
                    AccountService.calculate_raiffeisenbank_payment_schedule(
                        card, purchase_start
                    )
                )
                if raiffeisen_schedule:
                    final_debt = raiffeisen_schedule['final_debt']

            history.append(
                {
                    'month': purchase_start.strftime('%m.%Y'),
                    'debt': debt_for_month,
                    'final_debt': final_debt,
                    'grace_end': grace_end.strftime('%d.%m.%Y'),
                    'is_overdue': is_overdue,
                }
            )
        all_payments = list(
            Income.objects.filter(account=card)
            .order_by('date')
            .values('amount', 'date'),
        )
        total_payments = sum([float(p['amount']) for p in all_payments])
        payments_left = total_payments
        for m in months:
            debt = float(m['debt_for_month'])
            if debt <= 0:
                m['payments_made'] = 0
                m['remaining_debt'] = 0
                m['is_paid'] = True
                continue
            paid = min(payments_left, debt)
            m['payments_made'] = paid
            m['remaining_debt'] = max(debt - paid, 0)
            m['is_paid'] = m['remaining_debt'] <= 0
            payments_left -= paid
            if payments_left < 0:
                payments_left = 0
        for m in months:
            if m['debt_for_month'] > 0:
                # Для Райффайзенбанка используем правильную дату окончания льготного периода
                payment_due_date = m['grace_end'].strftime('%d.%m.%Y')
                if getattr(card, 'bank', None) == 'RAIFFAISENBANK':
                    # Находим соответствующую запись в истории для правильной даты
                    for h in history:
                        if h['month'] == m['month']:
                            payment_due_date = h['grace_end']
                            break

                payment_schedule.append(
                    {
                        'month': m['month'],
                        'sum_expense': m['debt_for_month'],
                        'payments_made': m['payments_made'],
                        'remaining_debt': m['remaining_debt'],
                        'payment_due': payment_due_date,
                        'is_overdue': m['is_overdue'],
                        'days_until_due': m['days_until_due'],
                        'is_paid': m['is_paid'],
                    }
                )
        current_month = today_month
        current_grace_info = card.calculate_grace_period_info(current_month)
        current_grace_info['debt_for_month'] = max(
            0, current_grace_info.get('debt_for_month', 0)
        )
        current_grace_info['final_debt'] = max(
            0, current_grace_info.get('final_debt', 0)
        )
        limit_left = (card.limit_credit or 0) - (debt_now or 0)
        credit_cards_data.append(
            {
                'name': card.name_account,
                'limit': card.limit_credit,
                'debt_now': debt_now,
                'current_grace_info': current_grace_info,
                'history': history,
                'currency': card.currency,
                'card_obj': card,
                'limit_left': limit_left,
                'payment_schedule': payment_schedule,
            }
        )
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
