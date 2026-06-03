from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from django.db.models import Avg, Count, Q, QuerySet, Sum
from django.db.models.functions import TruncMonth

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.receipts.models import Product, Receipt
from hasta_la_vista_money.transactions.models import (
    Category,
    Transaction,
)
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.monthly_statistics_service import (
    StatisticsChoiceDict,
    StatisticsFilters,
    _date_to_aware,
)


def _category_ids(keys: list[str], prefix: str) -> list[int]:
    return [
        int(value.removeprefix(prefix))
        for value in keys
        if value.startswith(prefix) and value.removeprefix(prefix).isdigit()
    ]


def _filter_transaction_queryset(
    queryset: QuerySet[Transaction],
    *,
    stats_filter: StatisticsFilters,
    type_value: str,
    start: date | None = None,
    end: date | None = None,
) -> QuerySet[Transaction]:
    if start is not None:
        queryset = queryset.filter(date__gte=_date_to_aware(start))
    if end is not None:
        queryset = queryset.filter(
            date__lte=_date_to_aware(end, end_of_day=True),
        )
    if stats_filter.account_ids:
        queryset = queryset.filter(account_id__in=stats_filter.account_ids)
    if stats_filter.currency:
        queryset = queryset.filter(account__currency=stats_filter.currency)

    category_ids = _category_ids(stats_filter.category_keys, f'{type_value}-')
    if category_ids:
        queryset = queryset.filter(category_id__in=category_ids)
    elif stats_filter.category_keys:
        queryset = queryset.none()
    return queryset


def _filtered_transactions(
    type_value: str,
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date | None = None,
    end: date | None = None,
) -> QuerySet[Transaction]:
    queryset = Transaction.objects.filter(user__in=users, type=type_value)
    return _filter_transaction_queryset(
        queryset,
        stats_filter=stats_filter,
        type_value=type_value,
        start=start,
        end=end,
    )


def _filtered_receipts(
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
    account: Account | None = None,
) -> QuerySet[Receipt]:
    queryset = Receipt.objects.filter(
        user__in=users,
        receipt_date__gte=_date_to_aware(start),
        receipt_date__lte=_date_to_aware(end, end_of_day=True),
    )
    if account is not None:
        queryset = queryset.filter(account=account)
    if stats_filter.account_ids:
        queryset = queryset.filter(account_id__in=stats_filter.account_ids)
    if stats_filter.currency:
        queryset = queryset.filter(account__currency=stats_filter.currency)
    if stats_filter.receipts_search:
        search = stats_filter.receipts_search
        lookup = (
            Q(seller__name_seller__icontains=search)
            | Q(account__name_account__icontains=search)
            | Q(user__username__icontains=search)
        )
        if search.isdigit():
            lookup |= Q(number_receipt=int(search))
        queryset = queryset.filter(lookup)
    if (
        stats_filter.category_keys
        and 'receipt' not in stats_filter.category_keys
    ):
        queryset = queryset.none()
    return queryset


def _filtered_accounts(
    accounts: QuerySet[Account],
    stats_filter: StatisticsFilters,
) -> QuerySet[Account]:
    if stats_filter.account_ids:
        accounts = accounts.filter(pk__in=stats_filter.account_ids)
    if stats_filter.currency:
        accounts = accounts.filter(currency=stats_filter.currency)
    return accounts


def _category_choices(users: Iterable[User]) -> list[StatisticsChoiceDict]:
    choices = [
        {
            'value': f'{category.type}-{category.pk}',
            'label': f'{category.name} ({category.get_type_display()})',
        }
        for category in Category.objects.filter(user__in=users).order_by(
            'type',
            'name',
        )
    ]
    choices.append({'value': 'receipt', 'label': 'Чеки'})
    return choices


def _sum_amount_for_period(
    type_value: str,
    users: Iterable[User],
    start: date,
    end: date,
    stats_filter: StatisticsFilters,
) -> float:
    queryset = _filtered_transactions(
        type_value,
        users,
        stats_filter,
        start=start,
        end=end,
    )
    return float(queryset.aggregate(total=Sum('amount'))['total'] or 0)


def _top_categories_qs(
    type_value: str,
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
) -> Any:
    queryset = _filtered_transactions(
        type_value,
        users,
        stats_filter,
        start=start,
        end=end,
    )
    return (
        queryset.values('category__id', 'category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[: constants.TOP_CATEGORIES_LIMIT]
    )


def _top_categories_with_comparison(
    type_value: str,
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    current = list(
        _top_categories_qs(type_value, users, stats_filter, start, end),
    )
    period_days = max(constants.ONE, (end - start).days + constants.ONE)
    previous_end = start - timedelta(days=constants.ONE)
    previous_start = previous_end - timedelta(days=period_days - constants.ONE)
    previous = {
        item['category__id']: float(item['total'] or 0)
        for item in _top_categories_qs(
            type_value,
            users,
            stats_filter,
            previous_start,
            previous_end,
        )
    }
    category_ids = [item['category__id'] for item in current]
    children = _category_children_totals(
        type_value,
        users,
        stats_filter,
        start,
        end,
        category_ids,
    )
    transactions = _category_drilldown_transactions(
        type_value,
        users,
        stats_filter,
        start,
        end,
        category_ids,
    )
    for item in current:
        total = float(item['total'] or 0)
        previous_total = previous.get(item['category__id'], 0.0)
        delta = total - previous_total
        item['previous_total'] = previous_total
        item['delta'] = delta
        item['delta_percent'] = (
            delta / previous_total * constants.PERCENTAGE_MULTIPLIER
            if previous_total
            else None
        )
        item['children'] = children.get(item['category__id'], [])
        item['transactions'] = transactions.get(item['category__id'], [])
    return current


def _category_children_totals(
    type_value: str,
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
    category_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    if not category_ids:
        return {}
    rows = (
        _filtered_transactions(
            type_value,
            users,
            stats_filter,
            start,
            end,
        )
        .filter(
            category__parent_category_id__in=category_ids,
        )
        .values(
            'category__parent_category_id',
            'category__id',
            'category__name',
        )
        .annotate(total=Sum('amount'))
        .order_by('category__parent_category_id', '-total')
    )
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[row['category__parent_category_id']].append(row)
    return result


def _category_drilldown_transactions(
    type_value: str,
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
    category_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    if not category_ids:
        return result
    queryset = _filtered_transactions(
        type_value,
        users,
        stats_filter,
        start,
        end,
    ).select_related('account', 'category', 'user')
    for category_id in category_ids:
        result[category_id] = list(
            queryset.filter(
                Q(category_id=category_id)
                | Q(category__parent_category_id=category_id),
            )
            .values(
                'date',
                'amount',
                'account__name_account',
                'category__name',
                'user__username',
            )
            .order_by('-date')[: constants.PAGINATE_BY_DEFAULT],
        )
    return result


def _match_income_expense_search(
    item: Any,
    search_value: str,
) -> bool:
    needle = search_value.lower().strip()
    if not needle:
        return True
    values = [
        str(item.get('category__name', '')),
        str(item.get('account__name_account', '')),
        str(item.get('user__username', '')),
        str(item.get('type', '')),
        str(item.get('date', '')),
        str(item.get('amount', '')),
    ]
    haystack = ' '.join(values).lower()
    return needle in haystack


def _transfer_logs(
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
) -> QuerySet[TransferMoneyLog]:
    if stats_filter.category_keys:
        return TransferMoneyLog.objects.none()

    queryset = (
        TransferMoneyLog.objects.filter(
            user__in=users,
            exchange_date__gte=_date_to_aware(start),
            exchange_date__lte=_date_to_aware(end, end_of_day=True),
        )
        .select_related('to_account', 'from_account', 'user')
        .order_by('-exchange_date')
    )
    if stats_filter.account_ids:
        queryset = queryset.filter(
            Q(from_account_id__in=stats_filter.account_ids)
            | Q(to_account_id__in=stats_filter.account_ids),
        )
    if stats_filter.currency:
        queryset = queryset.filter(
            Q(from_account__currency=stats_filter.currency)
            | Q(to_account__currency=stats_filter.currency),
        )
    if stats_filter.transfers_search:
        search = stats_filter.transfers_search
        queryset = queryset.filter(
            Q(from_account__name_account__icontains=search)
            | Q(to_account__name_account__icontains=search)
            | Q(user__username__icontains=search),
        )
    return queryset


def _receipt_details(
    users: Iterable[User],
    stats_filter: StatisticsFilters,
    start: date,
    end: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    receipts = _filtered_receipts(users, stats_filter, start, end)
    products = (
        Product.objects.filter(receipt_products__in=receipts)
        .values('product_name')
        .annotate(total=Sum('amount'), quantity=Sum('quantity'))
        .order_by('-total')[: constants.RECEIPT_RANK_LIMIT]
    )
    sellers = (
        receipts.values('seller__name_seller')
        .annotate(total=Sum('total_sum'), count=Count('id'))
        .order_by('-total')[: constants.RECEIPT_RANK_LIMIT]
    )
    averages = (
        receipts.annotate(month=TruncMonth('receipt_date'))
        .values('month')
        .annotate(avg_total=Avg('total_sum'), count=Count('id'))
        .order_by('month')
    )
    return list(products), list(sellers), list(averages)


__all__ = [
    '_category_children_totals',
    '_category_choices',
    '_category_drilldown_transactions',
    '_category_ids',
    '_filter_transaction_queryset',
    '_filtered_accounts',
    '_filtered_receipts',
    '_filtered_transactions',
    '_match_income_expense_search',
    '_receipt_details',
    '_sum_amount_for_period',
    '_top_categories_qs',
    '_top_categories_with_comparison',
    '_transfer_logs',
]
