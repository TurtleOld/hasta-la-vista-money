"""Views for finance account management.

This module provides Django views for managing financial accounts including
listing, creation, editing, deletion, and money transfer operations. Includes
comprehensive error handling, user authentication, and AJAX support.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlencode

import structlog
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView,
    DeleteView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)
from django_stubs_ext import StrOrPromise

from hasta_la_vista_money import constants
from hasta_la_vista_money.custom_mixin import DeleteObjectMixin
from hasta_la_vista_money.expense.forms import AddExpenseForm
from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.mixins import GroupAccountMixin
from hasta_la_vista_money.finance_account.models import (
    Account,
)
from hasta_la_vista_money.income.forms import IncomeForm
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.users.services.cache import (
    invalidate_user_detailed_statistics_cache,
)

if TYPE_CHECKING:
    from hasta_la_vista_money.core.types import (
        RequestWithContainer,
        WSGIRequestWithContainer,
    )

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FinancesCategoryChoice:
    """Category option used by the combined finances page."""

    key: str
    name: str
    type: str


@dataclass(frozen=True)
class FinancesTransaction:
    """Normalized income or expense row for finances rendering."""

    key: str
    source: str
    source_id: int | str
    date: Any
    amount: Decimal
    category_name: str
    category_key: str
    account_name: str
    user_name: str
    edit_url: str
    copy_url: str
    delete_url: str
    can_edit: bool
    is_receipt: bool = False

    @property
    def abs_amount(self) -> Decimal:
        """Return amount without sign."""

        return abs(self.amount)

    @property
    def type(self) -> str:
        """Return transaction type for UI state."""

        return 'income' if self.amount >= 0 else 'expense'


@dataclass(frozen=True)
class FinancesDayGroup:
    """Transactions grouped by calendar day."""

    date: date
    label: str
    items: list[FinancesTransaction]
    total: Decimal


@dataclass(frozen=True)
class FinancesCategoryGroup:
    """Transactions grouped by category."""

    key: str
    name: str
    type: str
    items: list[FinancesTransaction]
    total: Decimal
    average: Decimal
    share_pct: float
    bar_pct: float


@dataclass(frozen=True)
class FinancesSparkBar:
    """Daily positive and negative totals for the sparkbar."""

    label: str
    pos: Decimal
    neg: Decimal
    pos_pct: float
    neg_pct: float


@dataclass(frozen=True)
class FinancesSummary:
    """Aggregated values for the finances summary bar."""

    income: Decimal
    expense: Decimal
    net: Decimal
    avg_check: Decimal
    count: int
    spark: list[FinancesSparkBar]


@dataclass
class FinancesFilter:
    """GET parameters for the combined finances page."""

    type: str = 'all'
    period: str = 'm'
    account_ids: list[int] = field(default_factory=list)
    category_keys: list[str] = field(default_factory=list)
    min_amount: Decimal | None = None
    q: str = ''
    group_id: str = 'my'
    page: int = 1

    @classmethod
    def from_request(cls, request: Any) -> 'FinancesFilter':
        """Build filter object from request query parameters."""

        query = request.GET
        min_amount = None
        if query.get('min_amount'):
            try:
                min_amount = Decimal(query['min_amount'])
            except InvalidOperation:
                min_amount = None

        return cls(
            type=query.get('type', 'all'),
            period=query.get('period', 'm'),
            account_ids=[
                int(value)
                for value in query.getlist('account')
                if value.isdigit()
            ],
            category_keys=list(query.getlist('category')),
            min_amount=min_amount,
            q=query.get('q', '').strip(),
            group_id=query.get('group_id', 'my'),
            page=int(query.get('page', '1') or 1),
        )

    @property
    def is_active(self) -> bool:
        """Return whether at least one optional filter is active."""

        return bool(
            self.type != 'all'
            or self.period != 'm'
            or self.account_ids
            or self.category_keys
            or self.min_amount
            or self.q
            or self.group_id != 'my',
        )

    @property
    def query_string(self) -> str:
        """Return URL-encoded filter parameters without page."""

        params: list[tuple[str, str | int | Decimal]] = []
        if self.type != 'all':
            params.append(('type', self.type))
        if self.period != 'm':
            params.append(('period', self.period))
        if self.group_id != 'my':
            params.append(('group_id', self.group_id))
        params.extend(
            ('account', account_id) for account_id in self.account_ids
        )
        params.extend(
            ('category', category_key) for category_key in self.category_keys
        )
        if self.min_amount:
            params.append(('min_amount', self.min_amount))
        if self.q:
            params.append(('q', self.q))
        return urlencode(params)

    @property
    def period_label(self) -> str:
        """Return human readable selected period label."""

        labels = {
            'd': _('Сегодня'),
            'w': _('Неделя'),
            'm': _('Этот месяц'),
            'q': _('Квартал'),
            'y': _('Год'),
            'all': _('Всё время'),
        }
        return str(labels.get(self.period, labels['m']))

    @property
    def period_choices(self) -> list[tuple[str, str, str]]:
        """Return available period presets for the toolbar."""

        today = datetime.now(tz=UTC).date()
        quarter = ((today.month - 1) // 3) + 1
        return [
            ('d', str(_('Сегодня')), today.strftime('%d.%m')),
            ('w', str(_('Неделя')), str(_('пн-вс'))),
            ('m', str(_('Месяц')), today.strftime('%m.%Y')),
            (
                'q',
                str(_('{quarter} квартал')).format(quarter=quarter),
                '3 мес.',
            ),
            ('y', str(today.year), str(_('год'))),
            ('all', str(_('Всё время')), str(_('архив'))),
        ]

    def date_range(self) -> tuple[date, date] | None:
        """Return selected date range or None for all time."""

        today = datetime.now(tz=UTC).date()
        if self.period == 'd':
            return today, today
        if self.period == 'w':
            start = today - timedelta(days=today.weekday())
            return start, start + timedelta(days=6)
        if self.period == 'm':
            return today.replace(day=1), _end_of_month(today)
        if self.period == 'q':
            quarter = (today.month - 1) // 3
            start = date(today.year, quarter * 3 + 1, 1)
            return start, _end_of_month(date(today.year, quarter * 3 + 3, 1))
        if self.period == 'y':
            return date(today.year, 1, 1), date(today.year, 12, 31)
        return None


class FinancesView(LoginRequiredMixin, TemplateView):
    """Combined income and expense page."""

    template_name = 'finance_account/finances.html'

    def get_template_names(self) -> list[str]:
        """Use a partial template for HTMX list refreshes."""

        if self.request.headers.get('HX-Request') == 'true':
            return ['finance_account/partials/_finances_results.html']
        return [self.template_name]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Build combined finances context."""

        context = super().get_context_data(**kwargs)
        request = cast('WSGIRequestWithContainer', self.request)
        finances_filter = FinancesFilter.from_request(request)
        account_service = request.container.core.account_service()
        group_users = (
            account_service.get_users_for_group(
                request.user,
                finances_filter.group_id,
            )
            or []
        )
        users = group_users or [request.user]
        accounts = Account.objects.filter(user__in=users).order_by(
            'name_account',
        )
        categories = _finances_categories(users)
        transactions = _finances_transactions(
            request=request,
            users=users,
            finances_filter=finances_filter,
        )
        paginator = constants.PAGINATE_BY_DEFAULT
        page_obj = Paginator(transactions, paginator).get_page(
            finances_filter.page,
        )

        context.update(
            {
                'finances_filter': finances_filter,
                'accounts': accounts,
                'finances_categories': categories,
                'transactions': page_obj.object_list,
                'page_obj': page_obj,
                'summary': _finances_summary(transactions),
                'by_day': _group_finances_by_day(transactions),
                'by_category': _group_finances_by_category(transactions),
                'selected_group_id': finances_filter.group_id,
                'base_querystring': finances_filter.query_string,
            },
        )
        return context


class FinancesCreateView(LoginRequiredMixin, TemplateView):
    """Combined create view for income and expense operations."""

    template_name = 'finance_account/create.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Build context with both income and expense forms."""
        context = super().get_context_data(**kwargs)
        request = cast('WSGIRequestWithContainer', self.request)
        income_categories = IncomeCategory.objects.filter(user=request.user)
        expense_categories = ExpenseCategory.objects.filter(user=request.user)
        accounts = Account.objects.filter(user=request.user).order_by(
            'name_account',
        )
        context.update(
            {
                'income_categories': income_categories,
                'expense_categories': expense_categories,
                'accounts': accounts,
            },
        )
        return context

    def post(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        """Handle POST: create income or expense based on operation_type."""
        operation_type = request.POST.get('operation_type', 'expense')
        if operation_type == 'income':
            return self._create_income(request)
        return self._create_expense(request)

    def _create_income(self, request: Any) -> HttpResponse:
        typed_request = cast('RequestWithContainer', request)
        income_categories = IncomeCategory.objects.filter(user=request.user)
        accounts = Account.objects.filter(user=request.user)
        form = IncomeForm(
            request.POST,
            category_queryset=income_categories,
            account_queryset=accounts,
        )
        if not form.is_valid():
            messages.error(request, _('Пожалуйста, исправьте ошибки в форме.'))
            return HttpResponseRedirect(reverse('finances_create'))
        cd = form.cleaned_data
        try:
            income_ops = typed_request.container.income.income_ops()
            income_ops.add_income(
                user=request.user,
                account=cd['account'],
                category=cd['category'],
                amount=cd['amount'],
                income_date=cd['date'],
            )
            messages.success(request, constants.SUCCESS_INCOME_ADDED)
        except (ValueError, TypeError, PermissionDenied):
            messages.error(request, _('Ошибка при создании дохода.'))
        return HttpResponseRedirect(reverse('finances'))

    def _create_expense(self, request: Any) -> HttpResponse:
        typed_request = cast('RequestWithContainer', request)
        expense_service = typed_request.container.expense.expense_service(
            user=request.user,
            request=request,
        )
        form = AddExpenseForm(
            request.POST,
            **expense_service.get_form_querysets(),
        )
        if not form.is_valid():
            messages.error(request, _('Пожалуйста, исправьте ошибки в форме.'))
            return HttpResponseRedirect(reverse('finances_create'))
        try:
            expense_service.create_expense(form)
            messages.success(request, constants.SUCCESS_EXPENSE_ADDED)
        except (ValueError, TypeError):
            messages.error(request, _('Ошибка при создании расхода.'))
        return HttpResponseRedirect(reverse('finances'))


def _end_of_month(value: date) -> date:
    december = 12
    if value.month == december:
        return date(value.year, december, 31)
    return date(value.year, value.month + 1, 1) - timedelta(days=1)


def _finances_categories(users: Iterable[User]) -> list[FinancesCategoryChoice]:
    income_categories = IncomeCategory.objects.filter(user__in=users)
    expense_categories = ExpenseCategory.objects.filter(user__in=users)
    categories = [
        FinancesCategoryChoice(
            key=f'income-{category.pk}',
            name=category.name,
            type='income',
        )
        for category in income_categories
    ]
    categories.extend(
        FinancesCategoryChoice(
            key=f'expense-{category.pk}',
            name=category.name,
            type='expense',
        )
        for category in expense_categories
    )
    return sorted(categories, key=lambda item: (item.type, item.name))


def _category_ids(keys: list[str], prefix: str) -> list[int]:
    return [
        int(value.removeprefix(prefix))
        for value in keys
        if value.startswith(prefix) and value.removeprefix(prefix).isdigit()
    ]


def _apply_date_filter(queryset: QuerySet[Any], field: str, f: FinancesFilter):
    date_range = f.date_range()
    if date_range is None:
        return queryset
    start, end = date_range
    return queryset.filter(
        **{
            f'{field}__date__gte': start,
            f'{field}__date__lte': end,
        },
    )


def _finances_transactions(
    *,
    request: 'WSGIRequestWithContainer',
    users: list[User],
    finances_filter: FinancesFilter,
) -> list[FinancesTransaction]:
    transactions: list[FinancesTransaction] = []
    if finances_filter.type in {'all', 'income'}:
        transactions.extend(
            _income_transactions(request.user, users, finances_filter),
        )
    if finances_filter.type in {'all', 'expense'}:
        transactions.extend(
            _expense_transactions(request, users, finances_filter),
        )
    return sorted(transactions, key=lambda item: item.date, reverse=True)


def _income_transactions(
    current_user: User,
    users: list[User],
    finances_filter: FinancesFilter,
) -> list[FinancesTransaction]:
    queryset = Income.objects.filter(user__in=users).select_related(
        'account',
        'category',
        'user',
    )
    queryset = _apply_date_filter(queryset, 'date', finances_filter)
    if finances_filter.account_ids:
        queryset = queryset.filter(account_id__in=finances_filter.account_ids)
    income_category_ids = _category_ids(
        finances_filter.category_keys,
        'income-',
    )
    if income_category_ids:
        queryset = queryset.filter(category_id__in=income_category_ids)
    elif finances_filter.category_keys:
        queryset = queryset.none()
    if finances_filter.min_amount:
        queryset = queryset.filter(amount__gte=finances_filter.min_amount)
    if finances_filter.q:
        queryset = queryset.filter(category__name__icontains=finances_filter.q)

    return [
        FinancesTransaction(
            key=f'income-{income.pk}',
            source='income',
            source_id=income.pk,
            date=income.date,
            amount=income.amount,
            category_name=income.category.name,
            category_key=f'income-{income.category_id}',
            account_name=income.account.name_account,
            user_name=income.user.username,
            edit_url=reverse('income:change', kwargs={'pk': income.pk}),
            copy_url=reverse('income:income_copy', kwargs={'pk': income.pk}),
            delete_url=reverse(
                'income:delete_income',
                kwargs={'pk': income.pk},
            ),
            can_edit=income.user_id == current_user.pk,
        )
        for income in queryset
    ]


def _expense_transactions(
    request: 'WSGIRequestWithContainer',
    users: list[User],
    finances_filter: FinancesFilter,
) -> list[FinancesTransaction]:
    queryset = Expense.objects.filter(user__in=users).select_related(
        'account',
        'category',
        'user',
    )
    queryset = _apply_date_filter(queryset, 'date', finances_filter)
    if finances_filter.account_ids:
        queryset = queryset.filter(account_id__in=finances_filter.account_ids)
    expense_category_ids = _category_ids(
        finances_filter.category_keys,
        'expense-',
    )
    if expense_category_ids:
        queryset = queryset.filter(category_id__in=expense_category_ids)
    elif finances_filter.category_keys:
        queryset = queryset.none()
    if finances_filter.min_amount:
        queryset = queryset.filter(amount__gte=finances_filter.min_amount)
    if finances_filter.q:
        queryset = queryset.filter(category__name__icontains=finances_filter.q)

    transactions = [
        FinancesTransaction(
            key=f'expense-{expense.pk}',
            source='expense',
            source_id=expense.pk,
            date=expense.date,
            amount=-expense.amount,
            category_name=expense.category.name,
            category_key=f'expense-{expense.category_id}',
            account_name=expense.account.name_account,
            user_name=expense.user.username,
            edit_url=reverse('expense:change', kwargs={'pk': expense.pk}),
            copy_url=reverse(
                'expense:expense_copy',
                kwargs={'pk': expense.pk},
            ),
            delete_url=reverse('expense:delete', kwargs={'pk': expense.pk}),
            can_edit=expense.user_id == request.user.pk,
        )
        for expense in queryset
    ]
    transactions.extend(
        _receipt_transactions(request, users, finances_filter),
    )
    return transactions


def _receipt_transactions(
    request: 'WSGIRequestWithContainer',
    users: list[User],
    finances_filter: FinancesFilter,
) -> list[FinancesTransaction]:
    if finances_filter.account_ids or finances_filter.category_keys:
        return []
    receipt_service = request.container.expense.receipt_expense_service(
        user=request.user,
        request=request,
    )
    receipt_items = (
        receipt_service.get_receipt_expenses_by_users(users)
        if len(users) > 1 or users[0] != request.user
        else receipt_service.get_receipt_expenses()
    )
    date_range = finances_filter.date_range()
    transactions = []
    for receipt in receipt_items:
        receipt_date = _receipt_value(receipt, 'date')
        amount = Decimal(str(_receipt_value(receipt, 'amount') or 0))
        category = _receipt_value(receipt, 'category')
        account = _receipt_value(receipt, 'account')
        user = _receipt_value(receipt, 'user')
        if (
            date_range
            and not date_range[0] <= _to_date(receipt_date) <= date_range[1]
        ):
            continue
        if finances_filter.min_amount and amount < finances_filter.min_amount:
            continue
        category_name = _receipt_nested_value(category, 'name')
        if (
            finances_filter.q
            and finances_filter.q.lower() not in category_name.lower()
        ):
            continue
        transactions.append(
            FinancesTransaction(
                key=str(_receipt_value(receipt, 'id')),
                source='receipt',
                source_id=str(_receipt_value(receipt, 'id')),
                date=receipt_date,
                amount=-amount,
                category_name=category_name,
                category_key='receipt',
                account_name=_receipt_nested_value(account, 'name_account'),
                user_name=_receipt_nested_value(user, 'username'),
                edit_url='',
                copy_url='',
                delete_url='',
                can_edit=False,
                is_receipt=True,
            ),
        )
    return transactions


def _receipt_value(receipt: Any, key: str) -> Any:
    if isinstance(receipt, dict):
        return receipt.get(key)
    return getattr(receipt, key)


def _receipt_nested_value(value: Any, key: str) -> str:
    if isinstance(value, dict):
        return str(value.get(key, ''))
    return str(getattr(value, key, ''))


def _finances_summary(
    transactions: list[FinancesTransaction],
) -> FinancesSummary:
    income = sum((tx.amount for tx in transactions if tx.amount > 0), Decimal())
    expense = sum(
        (tx.abs_amount for tx in transactions if tx.amount < 0),
        Decimal(),
    )
    total_abs = income + expense
    count = len(transactions)
    avg_check = total_abs / count if count else Decimal()
    return FinancesSummary(
        income=income,
        expense=expense,
        net=income - expense,
        avg_check=avg_check,
        count=count,
        spark=_finances_spark(transactions),
    )


def _finances_spark(
    transactions: list[FinancesTransaction],
) -> list[FinancesSparkBar]:
    today = datetime.now(tz=UTC).date()
    days = [today - timedelta(days=offset) for offset in range(13, -1, -1)]
    buckets = {day: {'pos': Decimal(), 'neg': Decimal()} for day in days}
    for tx in transactions:
        tx_date = _to_date(tx.date)
        if tx_date not in buckets:
            continue
        if tx.amount > 0:
            buckets[tx_date]['pos'] += tx.amount
        else:
            buckets[tx_date]['neg'] += tx.abs_amount
    maximum = max(
        [Decimal(1)]
        + [value for bucket in buckets.values() for value in bucket.values()],
    )
    return [
        FinancesSparkBar(
            label=day.strftime('%d.%m'),
            pos=bucket['pos'],
            neg=bucket['neg'],
            pos_pct=float(bucket['pos'] / maximum * 50),
            neg_pct=float(bucket['neg'] / maximum * 50),
        )
        for day, bucket in buckets.items()
    ]


def _group_finances_by_day(
    transactions: list[FinancesTransaction],
) -> list[FinancesDayGroup]:
    groups: dict[date, list[FinancesTransaction]] = {}
    for tx in transactions:
        groups.setdefault(_to_date(tx.date), []).append(tx)
    return [
        FinancesDayGroup(
            date=group_date,
            label=_day_label(group_date),
            items=items,
            total=sum((item.amount for item in items), Decimal()),
        )
        for group_date, items in sorted(groups.items(), reverse=True)
    ]


def _group_finances_by_category(
    transactions: list[FinancesTransaction],
) -> list[FinancesCategoryGroup]:
    groups: dict[str, list[FinancesTransaction]] = {}
    for tx in transactions:
        groups.setdefault(tx.category_key, []).append(tx)
    totals = [
        abs(sum((item.amount for item in items), Decimal()))
        for items in groups.values()
    ]
    total_abs = sum(totals, Decimal()) or Decimal(1)
    max_abs = max(totals) if totals else Decimal(1)
    result = []
    for key, items in groups.items():
        total = sum((item.amount for item in items), Decimal())
        abs_total = abs(total)
        result.append(
            FinancesCategoryGroup(
                key=key,
                name=items[0].category_name,
                type=items[0].type,
                items=items,
                total=total,
                average=abs_total / len(items),
                share_pct=float(abs_total / total_abs * 100),
                bar_pct=float(abs_total / max_abs * 100),
            ),
        )
    return sorted(result, key=lambda item: abs(item.total), reverse=True)


def _day_label(value: date) -> str:
    today = datetime.now(tz=UTC).date()
    if value == today:
        return str(_('Сегодня'))
    if value == today - timedelta(days=1):
        return str(_('Вчера'))
    return value.strftime('%d.%m.%Y')


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return value.date()


class BaseView:
    """Base view class with common template and success URL configuration."""

    def get_template_name(self) -> str:
        """Get the template name to render."""
        return 'finance_account/account.html'

    def get_success_url(self) -> str | StrOrPromise | None:
        """Get the URL to redirect to after successful operation."""
        return reverse_lazy('finance_account:list')


class AccountBaseView(BaseView):
    """Base view class for account-related operations."""

    def get_queryset(self) -> QuerySet[Account]:
        """Get the queryset of accounts for the current user."""
        request_obj = getattr(self, 'request', None)
        if request_obj is None:
            raise AttributeError('request attribute is required')
        request = cast('WSGIRequestWithContainer', request_obj)
        if not isinstance(request.user, User):
            msg = 'User must be authenticated'
            raise TypeError(msg)
        return Account.objects.by_user(request.user)


class AccountView(
    LoginRequiredMixin,
    GroupAccountMixin,
    SuccessMessageMixin[Any],
    ListView[Account],
    AccountBaseView,
):
    """Display a list of user or group accounts with related forms
    and statistics.

    Shows all accounts for the current user or selected group, provides
    forms for adding and transferring accounts,
    and displays recent transfer logs and account balances. Supports
    group-based filtering and comprehensive
    financial data presentation.
    """

    context_object_name = 'finance_account'
    template_name = 'finance_account/account.html'

    def get_queryset(self) -> QuerySet[Account]:
        """Get the queryset of accounts for the current user or group.

        Uses GroupAccountMixin to get group_id and account_service
        to filter accounts by user or group.
        """
        request = cast('WSGIRequestWithContainer', self.request)
        account_service = request.container.core.account_service()
        group_id = self.get_group_id()
        return cast(
            'QuerySet[Account, Account]',
            account_service.get_accounts_for_user_or_group(
                request.user,
                group_id,
            ),
        )

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build the context for the account list page.

        Delegates context building to AccountPageContextService.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context for rendering the account list template.
        """
        context = super().get_context_data(
            object_list=object_list,
            **kwargs,
        )

        request = cast('WSGIRequestWithContainer', self.request)
        container = request.container.finance_account
        page_context_service = container.account_page_context_service()

        user = page_context_service.get_user_with_groups(
            request.user.pk,
        )
        group_id = self.get_group_id()
        accounts = page_context_service.get_accounts_for_user_or_group(
            user,
            group_id,
        )

        # Get balance trend period from query parameters
        balance_trend_period = request.GET.get('balance_trend_period', '30d')

        page_context = page_context_service.build_account_list_context(
            user,
            accounts,
            group_id=group_id,
            balance_trend_period=balance_trend_period,
        )

        context.update(page_context)
        return context


class AccountCreateView(
    LoginRequiredMixin,
    CreateView[Account, AddAccountForm],
    AccountBaseView,
):
    """
    Handles creation of a new account for the current user.

    Presents a form for account creation, validates and saves the
    account, and provides user feedback.
    """

    form_class = AddAccountForm
    template_name = 'finance_account/add_account.html'
    no_permission_url = reverse_lazy('login')
    success_message = constants.SUCCESS_MESSAGE_ADDED_ACCOUNT

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Add the account creation form to the context.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context with the account creation form.
        """
        context = super().get_context_data(
            object_list=object_list,
            **kwargs,
        )
        context['add_account_form'] = AddAccountForm()
        return context

    def get_success_url(self) -> str:
        """
        Get the URL to redirect to after successful account creation.

        Returns:
            str: Success redirect URL.
        """
        return str(reverse_lazy('finance_account:list'))

    def form_valid(self, form: AddAccountForm) -> HttpResponseRedirect:
        """
        Save the new account and handle success or error feedback.

        Args:
            form (AddAccountForm): The validated account creation form.

        Returns:
            HttpResponseRedirect: Redirect response after processing the form.
        """
        request = cast('WSGIRequestWithContainer', self.request)
        try:
            account = form.save(commit=False)
            if not isinstance(request.user, User):
                raise TypeError('User must be authenticated')
            account.user = request.user
            account.save()
            invalidate_user_detailed_statistics_cache(request.user.pk)
            messages.success(request, self.success_message)
            return HttpResponseRedirect(self.get_success_url())
        except Exception:
            logger.exception(
                'Ошибка при создании счета',
                user_id=getattr(request.user, 'id', None),
            )
            messages.error(
                request,
                _('Не удалось создать счет. Пожалуйста, попробуйте позже.'),
            )
            return HttpResponseRedirect(self.get_success_url())


class ChangeAccountView(
    LoginRequiredMixin,
    SuccessMessageMixin[AddAccountForm],
    UpdateView[Account, AddAccountForm],
    AccountBaseView,
):
    """
    Handles editing of an existing account.

    Presents a form for editing account details and provides user
    feedback on success or error.
    """

    model = Account
    form_class = AddAccountForm
    template_name = 'finance_account/change_account.html'
    success_message = constants.SUCCESS_MESSAGE_CHANGED_ACCOUNT

    def get_context_data(
        self,
        *,
        object_list: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Add the account edit form to the context.

        Args:
            **kwargs: Additional context parameters.

        Returns:
            dict: Context with the account edit form.
        """
        try:
            context = super().get_context_data(
                object_list=object_list,
                **kwargs,
            )
            form_class = self.get_form_class()
            form = form_class(**self.get_form_kwargs())
            context['add_account_form'] = form
        except Exception:
            request = cast('WSGIRequestWithContainer', self.request)
            logger.exception(
                'Ошибка при формировании контекста изменения счета',
                user_id=getattr(request.user, 'id', None),
            )
            messages.error(
                request,
                _(
                    'Произошла ошибка при загрузке формы изменения счета. '
                    'Пожалуйста, попробуйте позже.',
                ),
            )
            return super().get_context_data(
                object_list=object_list,
                **kwargs,
            )
        else:
            return context

    def form_valid(self, form: AddAccountForm) -> HttpResponseRedirect:
        request = cast('WSGIRequestWithContainer', self.request)
        try:
            account = form.save(commit=False)
            if not isinstance(request.user, User):
                raise TypeError('User must be authenticated')
            account.user = request.user
            account.save()
            invalidate_user_detailed_statistics_cache(request.user.pk)
            messages.success(request, self.success_message)
            return HttpResponseRedirect(str(self.get_success_url()))
        except ValidationError as e:
            form.add_error(None, str(e))
            messages.error(request, str(e))
            return self.form_invalid(form)  # type: ignore[return-value]
        except Exception:
            logger.exception(
                'Ошибка при изменении счета',
                user_id=getattr(request.user, 'id', None),
            )
            form.add_error(
                None,
                _('Не удалось изменить счет. Пожалуйста, попробуйте позже.'),
            )
            messages.error(
                request,
                _('Не удалось изменить счет. Пожалуйста, попробуйте позже.'),
            )
            return self.form_invalid(form)  # type: ignore[return-value]

    def form_invalid(self, form: AddAccountForm) -> Any:
        context = self.get_context_data()
        context['add_account_form'] = form
        return self.render_to_response(context)


class TransferMoneyAccountView(
    LoginRequiredMixin,
    SuccessMessageMixin[TransferMoneyAccountForm],
    FormView[TransferMoneyAccountForm],
    AccountBaseView,
):
    """
    Handles money transfers between user accounts.

    Validates and processes money transfer requests, providing user
    feedback and error handling.
    """

    form_class = TransferMoneyAccountForm
    success_message = constants.SUCCESS_MESSAGE_TRANSFER_MONEY
    template_name = 'finance_account/transfer_money.html'

    def get_form_kwargs(self) -> dict[str, Any]:
        """Get form kwargs including user for account filtering."""
        request = cast('WSGIRequestWithContainer', self.request)
        kwargs = super().get_form_kwargs()
        kwargs['user'] = request.user
        kwargs['transfer_service'] = (
            request.container.finance_account.transfer_service()
        )
        kwargs['account_repository'] = (
            request.container.finance_account.account_repository()
        )
        return kwargs

    def form_valid(
        self,
        form: TransferMoneyAccountForm,
    ) -> HttpResponseRedirect:
        """
        Process valid form submission.

        Args:
            form: Validated form instance.

        Returns:
            HttpResponseRedirect: Redirect to account list with success message.
        """
        request = cast('WSGIRequestWithContainer', self.request)
        try:
            cleaned_data = form.cleaned_data
            transfer_service = (
                request.container.finance_account.transfer_service()
            )
            transfer_service.transfer_money(
                from_account=cleaned_data['from_account'],
                to_account=cleaned_data['to_account'],
                amount=cleaned_data['amount'],
                user=cleaned_data['from_account'].user,
                exchange_date=cleaned_data.get('exchange_date'),
                notes=cleaned_data.get('notes'),
            )
            messages.success(request, self.success_message)
            return HttpResponseRedirect(reverse('finance_account:list'))
        except ValidationError as e:
            messages.error(request, str(e))
            return self.form_invalid(form)  # type: ignore[return-value]
        except Exception:
            logger.exception(
                'Ошибка при переводе средств между счетами',
                user_id=getattr(request.user, 'id', None),
            )
            messages.error(
                request,
                _(
                    'Произошла ошибка при переводе средств. '
                    'Пожалуйста, попробуйте позже.',
                ),
            )
            return self.form_invalid(form)  # type: ignore[return-value]


class DeleteAccountView(
    DeleteObjectMixin,
    LoginRequiredMixin,
    DeleteView[Account, Any],
):
    """
    Handles deletion of an account.

    Deletes the specified account and provides user feedback on
    success or failure.
    """

    model = Account
    template_name = 'finance_account/finance_account.html'
    success_url = reverse_lazy('finance_account:list')
    success_message = constants.SUCCESS_MESSAGE_DELETE_ACCOUNT[:]
    error_message = constants.UNSUCCESSFULLY_MESSAGE_DELETE_ACCOUNT[:]
