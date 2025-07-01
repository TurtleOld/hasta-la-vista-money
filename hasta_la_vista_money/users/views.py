import json
from collections import defaultdict
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, TemplateView, UpdateView
from django.views.generic.edit import FormView
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.generate_dates import generate_date_list
from hasta_la_vista_money.custom_mixin import (
    CustomNoPermissionMixin,
    CustomSuccessURLUserMixin,
)
from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income
from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.forms import (
    AddUserToGroupForm,
    DeleteUserFromGroupForm,
    GroupCreateForm,
    GroupDeleteForm,
    RegisterUserForm,
    UpdateUserForm,
    UserLoginForm,
)
from hasta_la_vista_money.users.models import User
from rest_framework_simplejwt.tokens import RefreshToken


class IndexView(TemplateView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('applications:list')
        return redirect('login')


class ListUsers(CustomNoPermissionMixin, SuccessMessageMixin, TemplateView):
    model = User
    template_name = 'users/profile.html'
    context_object_name = 'users'
    no_permission_url = reverse_lazy('login')

    def get_user_statistics(self, user):
        """Получение статистики пользователя"""
        today = timezone.now().date()
        month_start = today.replace(day=1)
        last_month = (month_start - timedelta(days=1)).replace(day=1)

        accounts_data = Account.objects.filter(user=user).aggregate(
            total_balance=Sum('balance'),
            accounts_count=Count('id'),
        )
        total_balance = accounts_data['total_balance'] or 0
        accounts_count = accounts_data['accounts_count'] or 0

        current_month_data = Expense.objects.filter(
            user=user,
            date__gte=month_start,
        ).aggregate(total=Sum('amount'))
        current_month_expenses = current_month_data['total'] or 0

        current_month_income_data = Income.objects.filter(
            user=user,
            date__gte=month_start,
        ).aggregate(total=Sum('amount'))
        current_month_income = current_month_income_data['total'] or 0

        last_month_expenses_data = Expense.objects.filter(
            user=user,
            date__gte=last_month,
            date__lt=month_start,
        ).aggregate(total=Sum('amount'))
        last_month_expenses = last_month_expenses_data['total'] or 0

        last_month_income_data = Income.objects.filter(
            user=user,
            date__gte=last_month,
            date__lt=month_start,
        ).aggregate(total=Sum('amount'))
        last_month_income = last_month_income_data['total'] or 0

        recent_expenses = (
            Expense.objects.filter(user=user)
            .select_related('category', 'account')
            .order_by('-date')[:5]
        )

        recent_incomes = (
            Income.objects.filter(user=user)
            .select_related('category', 'account')
            .order_by('-date')[:5]
        )

        receipts_count = Receipt.objects.filter(user=user).count()

        top_expense_categories = (
            Expense.objects.filter(user=user, date__gte=month_start)
            .values('category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:5]
        )

        return {
            'total_balance': total_balance,
            'accounts_count': accounts_count,
            'current_month_expenses': current_month_expenses,
            'current_month_income': current_month_income,
            'last_month_expenses': last_month_expenses,
            'last_month_income': last_month_income,
            'recent_expenses': recent_expenses,
            'recent_incomes': recent_incomes,
            'receipts_count': receipts_count,
            'top_expense_categories': top_expense_categories,
            'monthly_savings': current_month_income - current_month_expenses,
            'last_month_savings': last_month_income - last_month_expenses,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            user_update = UpdateUserForm(instance=self.request.user)
            user_update_pass_form = PasswordChangeForm(
                user=self.request.user,
            )
            user_statistics = self.get_user_statistics(self.request.user)

            context['user_update'] = user_update
            context['user_update_pass_form'] = user_update_pass_form
            context['user_statistics'] = user_statistics
            context['user'] = self.request.user
        return context


class LoginUser(SuccessMessageMixin, LoginView):
    model = User
    template_name = 'users/login.html'
    form_class = UserLoginForm
    success_message = constants.SUCCESS_MESSAGE_LOGIN
    next_page = reverse_lazy('applications:list')
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['button_text'] = _('Войти')
        context['user_login_form'] = UserLoginForm()
        if hasattr(self, 'jwt_access_token'):
            context['jwt_access_token'] = self.jwt_access_token
        if hasattr(self, 'jwt_refresh_token'):
            context['jwt_refresh_token'] = self.jwt_refresh_token
        return context

    def form_valid(self, form):
        username = form.cleaned_data['username']
        password = form.cleaned_data['password']
        user = authenticate(
            self.request,
            username=username,
            password=password,
            backend='django.contrib.auth.backends.ModelBackend',
        )
        if user is not None:
            login(self.request, user)
            tokens = RefreshToken.for_user(user)
            self.jwt_access_token = str(tokens.access_token)
            self.jwt_refresh_token = str(tokens)
            messages.success(self.request, self.success_message)
            if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse(
                    {
                        'access': self.jwt_access_token,
                        'refresh': self.jwt_refresh_token,
                        'redirect_url': self.get_success_url(),
                    },
                )
            return redirect(self.get_success_url())
        messages.error(self.request, _('Неправильный логин или пароль!'))
        return self.form_invalid(form)

    def form_invalid(self, form):
        if form.errors:
            error_message = list(form.errors.values())[0][0]
            if isinstance(error_message, str):
                messages.error(self.request, error_message)
            else:
                messages.error(self.request, str(error_message))
        return super().form_invalid(form)


class LogoutUser(LogoutView, SuccessMessageMixin):
    def dispatch(self, request, *args, **kwargs):
        messages.add_message(
            request,
            messages.SUCCESS,
            constants.SUCCESS_MESSAGE_LOGOUT,
        )
        return super().dispatch(request, *args, **kwargs)


class CreateUser(SuccessMessageMixin, CreateView):
    model = User
    template_name = 'users/registration.html'
    form_class = RegisterUserForm
    success_message = constants.SUCCESS_MESSAGE_REGISTRATION
    success_url = reverse_lazy('login')

    def dispatch(self, request, *args, **kwargs):
        if User.objects.filter(is_superuser=True).exists():
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = _('Форма регистрации')
        context['button_text'] = _('Регистрация')
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.is_superuser = True
        self.object.is_staff = True
        self.object.save()
        date_time_user_registration = self.object.date_joined
        generate_date_list(date_time_user_registration, self.object)
        return response


class UpdateUserView(
    CustomSuccessURLUserMixin,
    SuccessMessageMixin,
    UpdateView,
):
    model = User
    template_name = 'users/profile.html'
    form_class = UpdateUserForm
    success_message = constants.SUCCESS_MESSAGE_CHANGED_PROFILE

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.instance = self.request.user
        return form

    def post(self, request, *args, **kwargs):
        user_update = self.get_form()
        valid_form = (
            user_update.is_valid()
            and request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
        )
        if valid_form:
            user = user_update.save(commit=False)
            user.save()
            user_update.save_m2m()  # Сохраняем группы
            messages.success(request, self.success_message)
            response_data = {'success': True}
        else:
            response_data = {'success': False, 'errors': user_update.errors}
        return JsonResponse(response_data)


class SetPasswordUserView(LoginRequiredMixin, PasswordChangeView):
    template_name = 'users/set_password.html'
    form_class = SetPasswordForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, pk=self.request.user.pk)
        if self.request.method == 'POST':
            context['form_password'] = self.form_class(
                user=user,
                data=self.request.POST,
            )
            context['user'] = user
        else:
            context['form_password'] = self.form_class(user=user)
        return context

    def form_valid(self, form):
        form.save()
        update_session_auth_hash(request=self.request, user=form.user)
        messages.success(
            self.request,
            f'Пароль успешно установлен для пользователя {form.user}',
        )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy(
            'users:profile',
            kwargs={'pk': self.request.user.pk},
        )


class ExportUserDataView(LoginRequiredMixin, View):
    """Представление для экспорта данных пользователя"""

    def get(self, request, *args, **kwargs):
        user = request.user
        user_data = {
            'user_info': {
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'date_joined': user.date_joined.isoformat(),
                'last_login': user.last_login.isoformat() if user.last_login else None,
            },
            'accounts': list(
                Account.objects.filter(user=user).values(
                    'name_account',
                    'balance',
                    'currency',
                    'created_at',
                ),
            ),
            'expenses': list(
                Expense.objects.filter(user=user).values(
                    'amount',
                    'date',
                    'category__name',
                    'account__name_account',
                ),
            ),
            'incomes': list(
                Income.objects.filter(user=user).values(
                    'amount',
                    'date',
                    'category__name',
                    'account__name_account',
                ),
            ),
            'receipts': list(
                Receipt.objects.filter(user=user).values(
                    'receipt_date',
                    'seller__name_seller',
                    'total_sum',
                ),
            ),
            'statistics': {
                'total_balance': float(
                    Account.objects.filter(user=user).aggregate(total=Sum('balance'))[
                        'total'
                    ]
                    or 0,
                ),
                'total_expenses': float(
                    Expense.objects.filter(user=user).aggregate(total=Sum('amount'))[
                        'total'
                    ]
                    or 0,
                ),
                'total_incomes': float(
                    Income.objects.filter(user=user).aggregate(total=Sum('amount'))[
                        'total'
                    ]
                    or 0,
                ),
                'receipts_count': Receipt.objects.filter(user=user).count(),
            },
        }

        response = HttpResponse(
            json.dumps(user_data, ensure_ascii=False, indent=2, default=str),
            content_type='application/json',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="user_data_{user.username}_{timezone.now().strftime("%Y%m%d")}.json"'
        )

        return response


class UserStatisticsView(LoginRequiredMixin, TemplateView):
    """Представление для детальной статистики пользователя"""

    template_name = 'users/statistics.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

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
                },
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

        from hasta_la_vista_money.commonlogic.views import collect_info_receipt

        receipt_info_by_month = collect_info_receipt(user=user)

        from hasta_la_vista_money.finance_account.prepare import (
            collect_info_expense,
            collect_info_income,
            sort_expense_income,
        )

        income = collect_info_income(user)
        expenses = collect_info_expense(user)
        income_expense = sort_expense_income(expenses, income)

        from hasta_la_vista_money.finance_account.models import (
            TransferMoneyLog,
        )

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
                expense_amounts[expense_dates.index(date)]
                if date in expense_dates
                else 0
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

        context.update(
            {
                'months_data': months_data,
                'top_expense_categories': top_expense_categories,
                'top_income_categories': top_income_categories,
                'receipt_info_by_month': receipt_info_by_month,
                'income_expense': income_expense,
                'transfer_money_log': transfer_money_log,
                'accounts': accounts,
                'balances_by_currency': dict(balances_by_currency),
                'delta_by_currency': delta_by_currency,
                'chart_combined': chart_combined,
                'user': user,
            },
        )

        return context


class UserNotificationsView(LoginRequiredMixin, TemplateView):
    """Представление для уведомлений пользователя"""

    template_name = 'users/notifications.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        notifications = []

        # Проверяем различные условия для уведомлений
        today = timezone.now().date()
        month_start = today.replace(day=1)

        # Уведомление о низком балансе
        accounts = Account.objects.filter(user=user)
        low_balance_accounts = []
        for account in accounts:
            if float(account.balance) < 1000:  # Порог в 1000 рублей
                low_balance_accounts.append(account)

        if low_balance_accounts:
            notifications.append(
                {
                    'type': 'warning',
                    'title': 'Низкий баланс на счетах',
                    'message': f'На следующих счетах низкий баланс: {", ".join([acc.name_account for acc in low_balance_accounts])}',
                    'icon': 'bi-exclamation-triangle',
                },
            )

        # Уведомление о превышении расходов
        current_month_expenses = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(
                total=Sum('amount'),
            )['total']
            or 0
        )

        current_month_income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(
                total=Sum('amount'),
            )['total']
            or 0
        )

        if current_month_expenses > current_month_income:
            notifications.append(
                {
                    'type': 'danger',
                    'title': 'Превышение расходов',
                    'message': f'В текущем месяце расходы превышают доходы на {current_month_expenses - current_month_income:.2f} ₽',
                    'icon': 'bi-arrow-down-circle',
                },
            )

        # Уведомление о хороших сбережениях
        if (
            current_month_income > 0
            and (current_month_income - current_month_expenses) / current_month_income
            > 0.2
        ):
            notifications.append(
                {
                    'type': 'success',
                    'title': 'Отличные сбережения',
                    'message': 'Вы сэкономили более 20% от доходов в текущем месяце',
                    'icon': 'bi-check-circle',
                },
            )

        context.update(
            {
                'notifications': notifications,
                'user': user,
            },
        )

        return context


class GroupCreateView(LoginRequiredMixin, SuccessMessageMixin, FormView):
    template_name = 'users/group_create.html'
    form_class = GroupCreateForm
    success_message = _('Группа успешно создана')

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('users:profile', kwargs={'pk': self.request.user.pk})


class GroupDeleteView(LoginRequiredMixin, SuccessMessageMixin, FormView):
    template_name = 'users/group_delete.html'
    form_class = GroupDeleteForm
    success_message = _('Группа успешно удалена.')

    def form_valid(self, form):
        group = form.cleaned_data['group']
        group.delete()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('users:profile', kwargs={'pk': self.request.user.pk})


class AddUserToGroupView(LoginRequiredMixin, SuccessMessageMixin, FormView):
    template_name = 'users/add_user_to_group.html'
    form_class = AddUserToGroupForm
    success_message = _('Пользователь успешно добавлен в группу')

    def form_valid(self, form):
        user = form.cleaned_data['user']
        group = form.cleaned_data['group']
        user.groups.add(group)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('users:profile', kwargs={'pk': self.request.user.pk})


class DeleteUserFromGroupView(LoginRequiredMixin, SuccessMessageMixin, FormView):
    template_name = 'users/delete_user_from_group.html'
    form_class = DeleteUserFromGroupForm
    success_message = _('Пользователь успешно удален из группы')

    def form_valid(self, form):
        user = form.cleaned_data['user']
        print(user, 'user')
        group = form.cleaned_data['group']
        print(group, 'group')
        print(user.groups.all(), 'user.groups.all()')
        user.groups.remove(group)
        print(user.groups.all(), 'user.groups.all()')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('users:profile', kwargs={'pk': self.request.user.pk})


def groups_for_user_ajax(request):
    user_id = request.GET.get('user_id')
    groups = []
    if user_id:
        try:
            user = User.objects.get(pk=user_id)
            groups = list(user.groups.values('id', 'name'))
        except User.DoesNotExist:
            pass
    return JsonResponse({'groups': groups})


def groups_not_for_user_ajax(request):
    user_id = request.GET.get('user_id')
    groups = []
    if user_id:
        try:
            user = User.objects.get(pk=user_id)
            # Только те группы, в которые пользователь не входит
            from django.contrib.auth.models import Group

            groups = list(
                Group.objects.exclude(
                    id__in=user.groups.values_list('id', flat=True)
                ).values('id', 'name')
            )
        except User.DoesNotExist:
            pass
    return JsonResponse({'groups': groups})
