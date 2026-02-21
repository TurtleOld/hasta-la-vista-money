import json
import logging
import traceback
from decimal import Decimal
from operator import itemgetter
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from dateutil.parser import parse as parse_date
from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.db.models import QuerySet
from django.forms import BaseForm
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView
from django.views.generic.edit import FormView

from hasta_la_vista_money import constants
from hasta_la_vista_money.authentication.authentication import (
    clear_auth_cookies,
    set_auth_cookies,
)
from hasta_la_vista_money.core.types import RequestWithContainer
from hasta_la_vista_money.custom_mixin import CustomSuccessURLUserMixin
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.users.forms import (
    AddUserToGroupForm,
    BankStatementUploadForm,
    DeleteUserFromGroupForm,
    GroupCreateForm,
    GroupDeleteForm,
    RegisterUserForm,
    UpdateUserForm,
    UserLoginForm,
)
from hasta_la_vista_money.users.models import (
    BankStatementUpload,
    DashboardWidget,
    User,
)
from hasta_la_vista_money.users.services.auth import login_user
from hasta_la_vista_money.users.services.dashboard_analytics import (
    calculate_linear_trend,
    get_drill_down_data,
    get_period_comparison,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
    MonthDataDict,
    UserDetailedStatisticsDict,
    get_user_detailed_statistics,
)
from hasta_la_vista_money.users.services.export import get_user_export_data
from hasta_la_vista_money.users.services.groups import (
    create_group,
    delete_group,
    remove_user_from_group,
)
from hasta_la_vista_money.users.services.notifications import (
    get_user_notifications,
)
from hasta_la_vista_money.users.services.password import set_user_password
from hasta_la_vista_money.users.services.profile import update_user_profile
from hasta_la_vista_money.users.services.registration import register_user
from hasta_la_vista_money.users.services.theme import set_user_theme
from hasta_la_vista_money.users.tasks import (
    process_bank_statement_task,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class Transaction(TypedDict):
    id: int
    type: Literal['expense', 'income']
    date: str
    amount: str
    category: str
    account: str


class AuthRequest(RequestWithContainer):
    user: User


class IndexView(TemplateView):
    def dispatch(
        self,
        request: HttpRequest,
    ) -> HttpResponseBase:
        if request.user.is_authenticated:
            return redirect('finance_account:list')
        return redirect('login')


class ListUsers(
    LoginRequiredMixin,
    SuccessMessageMixin[BaseForm],
    TemplateView,
):
    model = User
    template_name = 'users/profile.html'
    context_object_name = 'users'
    no_permission_url = reverse_lazy('login')
    request: AuthRequest

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user_update = UpdateUserForm(instance=self.request.user)
        user_update_pass_form = PasswordChangeForm(
            user=self.request.user,
        )
        container = self.request.container
        statistics_service = container.users.user_statistics_service()
        user_statistics = statistics_service.get_user_statistics(
            self.request.user,
        )
        context['user_update'] = user_update
        context['user_update_pass_form'] = user_update_pass_form
        context['user_statistics'] = user_statistics
        context['user'] = self.request.user
        return context


class LoginUser(SuccessMessageMixin[UserLoginForm], LoginView):
    model = User
    template_name = 'users/login.html'
    form_class = UserLoginForm
    success_message = constants.SUCCESS_MESSAGE_LOGIN
    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        """Return the URL to redirect to after successful login."""
        return '/finance_account/'

    def dispatch(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        if not hasattr(request, 'axes_checked'):
            request.axes_checked = True  # type: ignore[attr-defined]
            if hasattr(request, 'axes_locked_out'):
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse(
                        {
                            'success': False,
                            'error': (
                                'Слишком много неудачных попыток входа. '
                                'Ваш браузер и компьютер заблокированы '
                                'для входа в это приложение. '
                                'Попробуйте позже или '
                                'обратитесь к администратору.'
                            ),
                        },
                        status=429,
                    )
                messages.error(
                    request,
                    'Слишком много неудачных попыток входа. '
                    'Ваш браузер и компьютер заблокированы '
                    'для входа в это приложение. '
                    'Попробуйте позже или обратитесь к администратору.',
                )
                return self.render_to_response(self.get_context_data())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['button_text'] = _('Войти')
        if 'form' in context:
            context['user_login_form'] = context['form']
        else:
            context['user_login_form'] = UserLoginForm()
        if hasattr(self, 'jwt_access_token'):
            context['jwt_access_token'] = self.jwt_access_token
        if hasattr(self, 'jwt_refresh_token'):
            context['jwt_refresh_token'] = self.jwt_refresh_token
        return context

    def form_valid(self, form: Any) -> HttpResponse:
        result = login_user(self.request, form, str(self.success_message))
        is_ajax = (
            self.request.headers.get('x-requested-with') == 'XMLHttpRequest'
        )

        if result.get('success'):
            self.jwt_access_token = result.get('access', '')
            self.jwt_refresh_token = result.get('refresh', '')
            if is_ajax:
                response: HttpResponse = JsonResponse(
                    {
                        'redirect_url': self.get_success_url(),
                    },
                )
            else:
                response = redirect(self.get_success_url())

            access_token: str | None = self.jwt_access_token
            refresh_token: str | None = self.jwt_refresh_token
            if access_token is None:
                return response
            return set_auth_cookies(
                response,
                access_token,
                refresh_token,
            )

        error_message = 'Неправильный логин или пароль!'
        messages.error(self.request, error_message)

        if is_ajax:
            return JsonResponse({'success': False, 'error': error_message})
        form.add_error(None, error_message)
        return self.form_invalid(form)

    def form_invalid(self, form: Any) -> HttpResponse:
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            errors = {}
            for field, field_errors in form.errors.items():
                error_msg = field_errors[0] if field_errors else ''
                errors[field] = error_msg
                if error_msg and field != '__all__':
                    messages.error(self.request, f'{field}: {error_msg}')

            if form.non_field_errors():
                for error in form.non_field_errors():
                    messages.error(self.request, str(error))

            return JsonResponse({'success': False, 'errors': errors})

        return self.render_to_response(self.get_context_data(form=form))


class LogoutUser(LogoutView, SuccessMessageMixin[BaseForm]):
    def dispatch(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        messages.add_message(
            request,
            messages.SUCCESS,
            constants.SUCCESS_MESSAGE_LOGOUT,
        )
        response = super().dispatch(request, *args, **kwargs)
        return clear_auth_cookies(response)


class CreateUser(
    SuccessMessageMixin[RegisterUserForm],
    CreateView[User, RegisterUserForm],
):
    model = User
    template_name = 'users/registration.html'
    form_class = RegisterUserForm
    success_message = constants.SUCCESS_MESSAGE_REGISTRATION
    success_url = reverse_lazy('login')

    def dispatch(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        if User.objects.filter(is_superuser=True).exists():
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context['title'] = _('Форма регистрации')
        context['button_text'] = _('Регистрация')
        return context

    def form_valid(self, form: RegisterUserForm) -> HttpResponse:
        response = super().form_valid(form)
        register_user(form)
        cache.delete('has_superuser')
        return response


class UpdateUserView(
    CustomSuccessURLUserMixin,
    SuccessMessageMixin[UpdateUserForm],
    UpdateView[User, UpdateUserForm],
):
    model = User
    template_name = 'users/profile.html'
    form_class = UpdateUserForm
    success_message = constants.SUCCESS_MESSAGE_CHANGED_PROFILE
    request: AuthRequest

    def get_form(self, form_class: Any = None) -> UpdateUserForm:
        form = super().get_form(form_class)
        form.instance = self.request.user
        return form

    def post(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        user_update = self.get_form()
        valid_form = (
            user_update.is_valid()
            and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
        )
        if valid_form:
            update_user_profile(user_update)
            messages.success(request, self.success_message)
            response_data = {'success': True, 'errors': {}}
        else:
            response_data = {'success': False, 'errors': user_update.errors}
        return JsonResponse(response_data)


class SetPasswordUserView(LoginRequiredMixin, PasswordChangeView):
    template_name = 'users/set_password.html'
    form_class = SetPasswordForm

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, pk=self.request.user.pk)
        if self.request.method == 'POST':
            context['form_password'] = SetPasswordForm(
                user=user,
                data=self.request.POST,
            )
            context['user'] = user
        else:
            context['form_password'] = SetPasswordForm(user=user)
        return context

    def form_valid(self, form: SetPasswordForm) -> HttpResponse:  # type: ignore[type-arg]
        set_user_password(form, self.request)
        messages.success(
            self.request,
            f'Пароль успешно установлен для пользователя {form.user}',
        )
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk},
            ),
        )


class ExportUserDataView(LoginRequiredMixin, View):
    """View for exporting user data.

    Provides JSON export of all user financial data including accounts,
    expenses, income, and receipts.
    """

    def get(
        self,
        request: HttpRequest,
    ) -> HttpResponse:
        if not isinstance(request.user, User):
            return HttpResponse('Unauthorized', status=401)
        user_data = get_user_export_data(request.user)
        response = HttpResponse(
            json.dumps(user_data, ensure_ascii=False, indent=2, default=str),
            content_type='application/json',
        )
        response['Content-Disposition'] = (
            'attachment; filename="user_data_{}_{}.json"'.format(
                request.user.username,
                timezone.now().strftime('%Y%m%d'),
            )
        )
        return response


class UserStatisticsView(LoginRequiredMixin, TemplateView):
    """View for user detailed statistics.

    Displays comprehensive user statistics including monthly data,
    top categories, and financial overview.
    """

    template_name = 'users/statistics.html'
    request: RequestWithContainer

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if isinstance(user, User):
            context.update(
                get_user_detailed_statistics(
                    user,
                    container=self.request.container,
                ).items(),
            )
        return context


class UserNotificationsView(LoginRequiredMixin, TemplateView):
    """View for user notifications.

    Displays user notifications including low balance warnings,
    expense over income alerts, and savings achievements.
    """

    template_name = 'users/notifications.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if isinstance(user, User):
            context['notifications'] = get_user_notifications(user)
        context['user'] = user
        return context


class GroupCreateView(
    LoginRequiredMixin,
    SuccessMessageMixin[GroupCreateForm],
    FormView[GroupCreateForm],
):
    template_name = 'users/group_create.html'
    form_class = GroupCreateForm
    success_message = _('Группа успешно создана')

    def form_valid(self, form: GroupCreateForm) -> HttpResponse:
        create_group(form)
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk or 0},
            ),
        )


class GroupDeleteView(
    LoginRequiredMixin,
    SuccessMessageMixin[GroupDeleteForm],
    FormView[GroupDeleteForm],
):
    template_name = 'users/group_delete.html'
    form_class = GroupDeleteForm
    success_message = _('Группа успешно удалена.')

    def form_valid(self, form: GroupDeleteForm) -> HttpResponse:
        delete_group(form)  # type: ignore[arg-type]
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk or 0},
            ),
        )


class AddUserToGroupView(
    LoginRequiredMixin,
    SuccessMessageMixin[AddUserToGroupForm],
    FormView[AddUserToGroupForm],
):
    template_name = 'users/add_user_to_group.html'
    form_class = AddUserToGroupForm
    success_message = _('Пользователь успешно добавлен в группу')

    def form_valid(self, form: AddUserToGroupForm) -> HttpResponse:
        form.save(self.request)
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk or 0},
            ),
        )


class DeleteUserFromGroupView(
    LoginRequiredMixin,
    SuccessMessageMixin[DeleteUserFromGroupForm],
    FormView[DeleteUserFromGroupForm],
):
    template_name = 'users/delete_user_from_group.html'
    form_class = DeleteUserFromGroupForm
    success_message = _('Пользователь успешно удален из группы')

    def form_valid(self, form: DeleteUserFromGroupForm) -> HttpResponse:
        remove_user_from_group(
            self.request,
            form.cleaned_data['user'],
            form.cleaned_data['group'],
        )
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return str(
            reverse_lazy(
                'users:profile',
                kwargs={'pk': self.request.user.pk or 0},
            ),
        )


class SwitchThemeView(LoginRequiredMixin, View):
    def post(
        self,
        request: HttpRequest,
    ) -> JsonResponse:
        try:
            user = User.objects.get(pk=request.user.pk)
            data = json.loads(request.body)
            theme = data.get('theme', 'light')

            if theme not in ['light', 'dark']:
                return JsonResponse(
                    {'success': False, 'error': 'Invalid theme'},
                    status=400,
                )

            set_user_theme(user, theme)
            return JsonResponse({'success': True, 'theme': theme})
        except json.JSONDecodeError:
            return JsonResponse(
                {'success': False, 'error': 'Invalid JSON'},
                status=400,
            )
        except User.DoesNotExist:
            return JsonResponse(
                {'success': False, 'error': 'User not found'},
                status=404,
            )


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
            {'type': 'trend', 'name': 'Тренды и прогнозы'},
            {'type': 'top_categories', 'name': 'Топ категорий'},
            {'type': 'recent_transactions', 'name': 'Последние операции'},
        ]

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
        stats: UserDetailedStatisticsDict,
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
        request: RequestWithContainer,
        *args: Any,
        **kwargs: Any,
    ) -> JsonResponse:
        try:
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

            cache_key = f'user_stats_{user.pk}'
            cache.delete(cache_key)

            stats: UserDetailedStatisticsDict = get_user_detailed_statistics(
                user,
                container=request.container,
            )

            serializable_stats = self._prepare_serializable_stats(
                stats,
            )

            months_data = serializable_stats.get('months_data', [])
            trends = self._calculate_trends(months_data)

            comparison_data = get_period_comparison(user, period)
            recent_transactions = self._get_recent_transactions(user)

            data = {
                'widgets': list(widgets.values()),
                'analytics': {
                    'stats': serializable_stats,
                    'trends': trends,
                },
                'comparison': comparison_data,
                'recent_transactions': recent_transactions,
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

        drill_data = get_drill_down_data(
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

        comparison_data = get_period_comparison(
            user=user,
            period_type=period_type,
        )

        return JsonResponse(comparison_data)


class BankStatementUploadView(
    LoginRequiredMixin,
    SuccessMessageMixin[BankStatementUploadForm],
    FormView[BankStatementUploadForm],
):
    """View for uploading bank statements in PDF format."""

    template_name = 'users/bank_statement_upload.html'
    form_class = BankStatementUploadForm
    success_message = _(
        'Банковская выписка загружена и будет обработана в фоновом режиме. '
        'Данные появятся в расходах и доходах в течение нескольких минут.',
    )
    request: AuthRequest

    def get_form_kwargs(self) -> dict[str, Any]:
        """Add user to form kwargs."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form: BankStatementUploadForm) -> HttpResponse:
        """Process uploaded PDF file asynchronously."""
        logger = logging.getLogger(__name__)
        pdf_file = form.cleaned_data['pdf_file']
        account = form.cleaned_data['account']

        try:
            logger.info(
                'Creating bank statement upload for user %s, account %s',
                self.request.user.username,
                account.name_account,
            )

            # Create upload record
            upload = BankStatementUpload.objects.create(
                user=self.request.user,
                account=account,
                pdf_file=pdf_file,
                status='pending',
            )

            logger.info('Created upload record with id=%d', upload.id)

            # Start background task
            task = process_bank_statement_task.delay(upload.id)
            logger.info('Started background task with id=%s', task.id)

            # Store upload ID in session for progress tracking
            self.request.session['last_upload_id'] = upload.id

            messages.success(self.request, str(self.success_message))

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.exception('Error creating upload record')
            messages.error(
                self.request,
                f'Произошла ошибка при загрузке файла: {e!s}',
            )
            return self.form_invalid(form)

        return super().form_valid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Add extra context data."""
        context = super().get_context_data(**kwargs)
        # Check if there's an ongoing upload
        last_upload_id = self.request.session.get('last_upload_id')
        if last_upload_id:
            try:
                upload = BankStatementUpload.objects.get(
                    id=last_upload_id,
                    user=self.request.user,
                )
                # Show progress if not completed
                if upload.status in ['pending', 'processing']:
                    context['show_progress'] = True
                    context['upload_id'] = upload.id
                elif upload.status == 'completed':
                    # Clear session if completed
                    self.request.session.pop('last_upload_id', None)
            except BankStatementUpload.DoesNotExist:
                # Clear invalid session data
                self.request.session.pop('last_upload_id', None)
        return context

    def get_success_url(self) -> str:
        """Return URL to redirect after successful upload."""
        # Redirect back to the same page to show progress
        return str(reverse_lazy('users:bank_statement_upload'))


class BankStatementUploadStatusView(LoginRequiredMixin, View):
    """View for checking bank statement upload progress."""

    def get(
        self,
        request: HttpRequest,
        upload_id: int,
    ) -> JsonResponse:
        """Get upload status and progress.

        Args:
            request: HTTP request.
            upload_id: ID of the upload to check.

        Returns:
            JSON response with upload status and progress.
        """
        try:
            upload = BankStatementUpload.objects.get(
                id=upload_id,
                user=request.user,
            )

            return JsonResponse(
                {
                    'status': upload.status,
                    'progress': upload.progress,
                    'total_transactions': upload.total_transactions,
                    'processed_transactions': upload.processed_transactions,
                    'income_count': upload.income_count,
                    'expense_count': upload.expense_count,
                    'error_message': upload.error_message,
                },
            )

        except BankStatementUpload.DoesNotExist:
            return JsonResponse(
                {'error': 'Upload not found'},
                status=404,
            )
