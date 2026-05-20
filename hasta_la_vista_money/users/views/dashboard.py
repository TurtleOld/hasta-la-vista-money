import json
import logging
import traceback
from collections.abc import Mapping
from decimal import Decimal
from operator import itemgetter
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast
from urllib.parse import urlencode

from dateutil.parser import parse as parse_date
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet
from django.http import (
    HttpRequest,
    JsonResponse,
)
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import TemplateView

from hasta_la_vista_money import constants
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.users.models import (
    DashboardWidget,
    User,
)
from hasta_la_vista_money.users.services.dashboard_analytics import (
    calculate_linear_trend,
)
from hasta_la_vista_money.users.services.dashboard_kpis import (
    DashboardKpiDict,
    get_dashboard_month_kpis,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
    DashboardSummaryStatisticsDict,
    MonthDataDict,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from hasta_la_vista_money.core.types import RequestWithContainer
import sys


def _views_module() -> Any:
    return sys.modules['hasta_la_vista_money.users.views']


class Transaction(TypedDict):
    id: int
    type: Literal['expense', 'income']
    date: str
    amount: str
    category: str
    account: str


class DashboardKpiCard(TypedDict):
    title: str
    value: Decimal | str
    subtitle: str
    url: str
    tone: str


def _operation_list_url(
    url_name: str,
    period_start: Any,
    period_end: Any,
    extra_params: dict[str, Any] | None = None,
) -> str:
    params = {
        'date_after': period_start.isoformat(),
        'date_before': period_end.isoformat(),
    }
    if extra_params:
        params.update(extra_params)
    return f'{reverse(url_name)}?{urlencode(params)}'


def _build_kpi_cards(kpis: DashboardKpiDict) -> list[DashboardKpiCard]:
    period_start = kpis['period_start']
    period_end = kpis['period_end']
    expense_url = _operation_list_url(
        'expense:list',
        period_start,
        period_end,
    )
    income_url = _operation_list_url('income:list', period_start, period_end)
    top_category_id = kpis['top_expense_category_id']
    top_category_url = (
        _operation_list_url(
            'expense:list',
            period_start,
            period_end,
            {'category': top_category_id},
        )
        if top_category_id is not None
        else expense_url
    )

    return [
        {
            'title': _('Доходы за месяц'),
            'value': kpis['income'],
            'subtitle': _('Открыть доходы периода'),
            'url': income_url,
            'tone': 'green',
        },
        {
            'title': _('Расходы за месяц'),
            'value': kpis['expenses'],
            'subtitle': _('Открыть расходы периода'),
            'url': expense_url,
            'tone': 'red',
        },
        {
            'title': _('Итог месяца'),
            'value': kpis['net_result'],
            'subtitle': _('Накоплено: %(rate).1f%%')
            % {'rate': kpis['savings_rate']},
            'url': income_url,
            'tone': 'blue' if kpis['net_result'] >= constants.ZERO else 'red',
        },
        {
            'title': _('Топ категория'),
            'value': kpis['top_expense_category_total'],
            'subtitle': kpis['top_expense_category_name'] or _('Нет расходов'),
            'url': top_category_url,
            'tone': 'amber',
        },
    ]


class DashboardView(LoginRequiredMixin, TemplateView):
    """View for dashboard page.

    Displays user dashboard with customizable widgets showing
    financial overview and analytics.
    """

    template_name = 'users/dashboard.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        context['default_period'] = 'month'
        context['available_widgets'] = [
            {'type': 'balance', 'name': 'Баланс счетов'},
            {'type': 'expenses_chart', 'name': 'График расходов'},
            {'type': 'income_chart', 'name': 'График доходов'},
            {'type': 'comparison', 'name': 'Сравнение периодов'},
            {'type': 'trend', 'name': 'Динамика и прогнозы'},
            {'type': 'top_categories', 'name': 'Топ категорий'},
            {'type': 'recent_transactions', 'name': 'Последние операции'},
        ]
        user = self.request.user
        if isinstance(user, User):
            context['kpi_cards'] = _build_kpi_cards(
                get_dashboard_month_kpis(user),
            )

        return context


class DashboardDataView(LoginRequiredMixin, View):
    """View for getting all dashboard data in JSON format.

    Provides JSON endpoint for dashboard widgets to fetch financial
    data including accounts, expenses, income, and analytics.
    """

    def _serialize_account(self, account: Account) -> dict[str, Any]:
        """Serialize account to dictionary.

        Args:
            account: Account instance to serialize.

        Returns:
            Dictionary with account data.
        """
        return {
            'id': account.pk,
            'name_account': account.name_account,
            'type_account': account.type_account,
            'balance': str(account.balance),
            'currency': account.currency,
            'bank': account.bank,
            'limit_credit': (
                str(account.limit_credit) if account.limit_credit else None
            ),
            'payment_due_date': (
                account.payment_due_date.isoformat()
                if account.payment_due_date
                else None
            ),
            'grace_period_days': account.grace_period_days,
        }

    def _serialize_transfer_log(
        self,
        transfer_log: TransferMoneyLog,
    ) -> dict[str, Any]:
        """Serialize TransferMoneyLog object to dictionary.

        Args:
            transfer_log: TransferMoneyLog instance to serialize.

        Returns:
            Dictionary with transfer log data.
        """
        return {
            'id': transfer_log.pk,
            'user_id': transfer_log.user.pk,
            'from_account': self._serialize_value(transfer_log.from_account),
            'to_account': self._serialize_value(transfer_log.to_account),
            'amount': str(transfer_log.amount),
            'exchange_date': transfer_log.exchange_date.isoformat(),
            'notes': transfer_log.notes,
            'created_at': (
                transfer_log.created_at.isoformat()
                if transfer_log.created_at
                else None
            ),
            'updated_at': (
                transfer_log.updated_at.isoformat()
                if transfer_log.updated_at
                else None
            ),
        }

    def _serialize_user(self, user: Any) -> dict[str, Any]:
        """Serialize User object to dictionary.

        Args:
            user: User instance to serialize.

        Returns:
            Dictionary with user data.
        """
        return {
            'id': user.pk,
            'username': user.username,
        }

    def _serialize_model(self, model_instance: Any) -> dict[str, Any]:
        """Serialize Django model instance to dictionary.

        Args:
            model_instance: Django model instance to serialize.

        Returns:
            Dictionary with model ID and class name.
        """
        return {
            'id': model_instance.pk,
            'model': model_instance.__class__.__name__,
        }

    def _serialize_value(self, value: Any) -> Any:
        """Recursively serialize value.

        Args:
            value: Value to serialize (can be model, dict, list, etc.).

        Returns:
            Serialized value suitable for JSON.
        """
        if isinstance(value, QuerySet | list | tuple):
            return [self._serialize_value(item) for item in value]
        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}

        type_serializers: dict[type[Any], Callable[[Any], dict[str, Any]]] = {
            Account: self._serialize_account,
            TransferMoneyLog: self._serialize_transfer_log,
        }
        serializer = type_serializers.get(type(value))
        if serializer:
            return serializer(value)

        if hasattr(value, '__class__') and value.__class__.__name__ == 'User':
            return self._serialize_user(value)
        if hasattr(value, '_meta'):
            return self._serialize_model(value)
        return value

    def _prepare_serializable_stats(
        self,
        stats: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Prepare statistics for serialization.

        Args:
            stats: User detailed statistics dictionary.

        Returns:
            Dictionary with serialized statistics values.
        """
        return {
            key: self._serialize_value(value) for key, value in stats.items()
        }

    def _calculate_trends(
        self,
        months_data: list[MonthDataDict],
    ) -> dict[str, Any]:
        """Calculate trends based on monthly data.

        Args:
            months_data: List of monthly data dictionaries.

        Returns:
            Dictionary with trend calculations (slope, intercept, etc.).
        """
        trends: dict[str, Any] = {}
        if not months_data:
            return trends

        dates = []
        expenses_values = []
        for m in months_data:
            try:
                month_str = m.get('month', '')
                parsed_date = parse_date(month_str, dayfirst=False)
                dates.append(parsed_date.date().replace(day=1))
                expenses_values.append(Decimal(str(m.get('expenses', 0))))
            except (ValueError, TypeError, AttributeError):
                continue

        if dates and expenses_values and len(dates) == len(expenses_values):
            trends = calculate_linear_trend(dates, expenses_values)

        return trends

    def _get_recent_transactions(self, user: User) -> list[Transaction]:
        """Get recent transactions for user.

        Args:
            user: User to get transactions for.

        Returns:
            List of Transaction dictionaries sorted by date descending.
        """
        recent_expenses = (
            Expense.objects.filter(user=user)
            .select_related('category', 'account')
            .order_by('-date')[: constants.RECENT_ITEMS_LIMIT]
        )
        recent_incomes = (
            Income.objects.filter(user=user)
            .select_related('category', 'account')
            .order_by('-date')[: constants.RECENT_ITEMS_LIMIT]
        )

        expense_transactions: list[Transaction] = [
            {
                'id': expense.pk,
                'type': 'expense',
                'date': expense.date.isoformat(),
                'amount': str(expense.amount),
                'category': expense.category.name,
                'account': expense.account.name_account,
            }
            for expense in recent_expenses
        ]
        income_transactions: list[Transaction] = [
            {
                'id': income.pk,
                'type': 'income',
                'date': income.date.isoformat(),
                'amount': str(income.amount),
                'category': income.category.name,
                'account': income.account.name_account,
            }
            for income in recent_incomes
        ]

        transactions = expense_transactions + income_transactions
        transactions.sort(key=itemgetter('date'), reverse=True)

        return transactions[: constants.RECENT_ITEMS_LIMIT]

    def get(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        try:
            request_with_container = cast('RequestWithContainer', request)
            user = request.user
            if not isinstance(user, User):
                return JsonResponse(
                    {'error': 'User not authenticated'},
                    status=401,
                )

            period = request.GET.get('period', 'month')

            widgets = DashboardWidget.objects.filter(
                user=user,
                is_visible=True,
            ).order_by('position')

            stats: DashboardSummaryStatisticsDict = (
                _views_module().get_dashboard_summary_statistics(
                    user,
                    container=request_with_container.container,
                )
            )

            serializable_stats = self._prepare_serializable_stats(
                stats,
            )

            months_data = serializable_stats.get('months_data', [])
            trends = self._calculate_trends(months_data)

            comparison_data = _views_module().get_period_comparison(
                user,
                period,
            )
            recent_transactions = self._get_recent_transactions(user)

            data = {
                'widgets': list(widgets.values()),
                'analytics': {
                    'stats': serializable_stats,
                    'trends': trends,
                },
                'comparison': comparison_data,
                'recent_transactions': recent_transactions,
                'click_through': {
                    'expense_list_url': reverse('expense:list'),
                    'income_list_url': reverse('income:list'),
                },
            }

            return JsonResponse(data, safe=False)
        except (
            ValueError,
            TypeError,
            AttributeError,
            KeyError,
            RuntimeError,
        ) as e:
            error_msg = str(e)
            traceback_str = traceback.format_exc()
            logger = logging.getLogger(__name__)
            logger.exception('Dashboard data loading error')
            return JsonResponse(
                {
                    'error': f'Internal server error: {error_msg}',
                    'traceback': traceback_str,
                },
                status=500,
            )


class DashboardWidgetConfigView(LoginRequiredMixin, View):
    """View for managing dashboard widget configuration.

    Handles creation, update, and deletion of dashboard widgets
    with their position, size, and visibility settings.
    """

    def post(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        user = request.user
        if not isinstance(user, User):
            return JsonResponse({'error': 'User not authenticated'}, status=401)

        data = json.loads(request.body)
        action = data.get('action')

        if action == 'delete':
            widget_id = data.get('widget_id')
            if not widget_id:
                return JsonResponse({'error': 'widget_id required'}, status=400)

            widget = get_object_or_404(
                DashboardWidget,
                id=widget_id,
                user=user,
            )
            widget.delete()
            return JsonResponse({'status': 'ok'})

        widget_id = data.get('widget_id')
        widget_type = data.get('widget_type')
        config = data.get('config', {})
        position = data.get('position', 0)
        width = data.get('width')
        height = data.get('height')

        if widget_id:
            widget = get_object_or_404(
                DashboardWidget,
                id=widget_id,
                user=user,
            )
            widget.config = config
            widget.position = position
            if width is not None:
                widget.width = width
            if height is not None:
                widget.height = height
            if 'is_visible' in data:
                widget.is_visible = data['is_visible']
            widget.save()
        else:
            widget = DashboardWidget.objects.create(
                user=user,
                widget_type=widget_type,
                config=config,
                position=position,
                width=width if width is not None else 6,
                height=height if height is not None else 300,
            )

        return JsonResponse(
            {
                'status': 'ok',
                'widget_id': widget.pk,
            },
        )

    def delete(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        user = request.user
        if not isinstance(user, User):
            return JsonResponse({'error': 'User not authenticated'}, status=401)

        widget_id = request.GET.get('widget_id')
        if not widget_id:
            return JsonResponse({'error': 'widget_id required'}, status=400)

        widget = get_object_or_404(
            DashboardWidget,
            id=widget_id,
            user=user,
        )
        widget.delete()

        return JsonResponse({'status': 'ok'})


class DashboardDrillDownView(LoginRequiredMixin, View):
    """View for getting category drill-down data.

    Provides JSON endpoint for drill-down charts showing category
    details and subcategories.
    """

    def get(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        user = request.user
        if not isinstance(user, User):
            return JsonResponse({'error': 'User not authenticated'}, status=401)

        category_id = request.GET.get('category_id')
        date_str = request.GET.get('date')
        data_type = request.GET.get('type', 'expense')

        drill_data = _views_module().get_drill_down_data(
            user=user,
            category_id=category_id,
            date_str=date_str,
            data_type=data_type,
        )

        return JsonResponse(drill_data)


class DashboardComparisonView(LoginRequiredMixin, View):
    """View for period comparison data.

    Provides JSON endpoint for comparing current and previous
    periods (month, quarter, year).
    """

    def get(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        user = request.user
        if not isinstance(user, User):
            return JsonResponse({'error': 'User not authenticated'}, status=401)

        period_type = request.GET.get('period', 'month')

        comparison_data = _views_module().get_period_comparison(
            user=user,
            period_type=period_type,
        )

        return JsonResponse(comparison_data)
