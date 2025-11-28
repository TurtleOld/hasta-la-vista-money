"""Django репозиторий для Expense модели."""

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet, Sum
from django.db.models.functions import TruncMonth

from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.models import ExpenseCategory


class ExpenseRepository:
    """Репозиторий для работы с Expense моделью."""

    def get_by_id(self, expense_id: int) -> Expense:
        """Получить expense по ID."""
        return Expense.objects.get(pk=expense_id)

    def get_by_user(self, user: User) -> QuerySet[Expense]:
        """Получить все expenses пользователя."""
        return Expense.objects.filter(user=user).select_related(
            'user',
            'category',
            'account',
        )

    def get_by_user_and_group(
        self,
        user: User,
        group_id: str | None = None,
    ) -> QuerySet[Expense]:
        """Получить expenses пользователя или группы."""
        if not group_id or group_id == 'my':
            return Expense.objects.filter(user=user).select_related(
                'user',
                'category',
                'account',
            )

        user_with_groups = User.objects.prefetch_related('groups').get(
            pk=user.pk,
        )
        if user_with_groups.groups.filter(id=group_id).exists():
            group_users = list(User.objects.filter(groups__id=group_id))
            return Expense.objects.filter(user__in=group_users).select_related(
                'user',
                'category',
                'account',
            )

        return Expense.objects.none()

    def create_expense(self, **kwargs: object) -> Expense:
        """Создать новый expense."""
        return Expense.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Expense]:
        """Фильтровать expenses."""
        return Expense.objects.filter(**kwargs)

    def filter_by_user_and_date_range(
        self,
        user: User,
        start_date: datetime,
        end_date: datetime,
    ) -> QuerySet[Expense]:
        """Фильтровать expenses пользователя за период."""
        return Expense.objects.filter(
            user=user,
            date__gte=start_date,
            date__lte=end_date,
        )

    def filter_by_user_and_account(
        self,
        user: User,
        account: Account,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> QuerySet[Expense, dict[str, Any]]:
        """Фильтровать expenses пользователя по счету и периоду."""
        qs = Expense.objects.filter(user=user, account=account)
        if start_date:
            qs = qs.filter(date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)
        return (
            qs.annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total=Sum('amount'))
        )

    def get_aggregated_by_date(
        self,
        user: User,
    ) -> QuerySet[Expense, dict[str, Any]]:
        """Получить агрегированные expenses по датам."""
        return (
            Expense.objects.filter(user=user)
            .values('date')
            .annotate(total_amount=Sum('amount'))
            .order_by('date')
        )

    def get_top_categories(
        self,
        user: User,
        year_start: datetime,
        limit: int = 10,
    ) -> QuerySet[Expense, dict[str, Any]]:
        """Получить топ категорий расходов."""
        return (
            Expense.objects.filter(user=user, date__gte=year_start)
            .values('category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:limit]
        )

    def filter_by_user_category_and_month(
        self,
        user: User,
        category: 'ExpenseCategory',
        month: date,
    ) -> QuerySet[Expense]:
        """Фильтровать expenses по пользователю, категории и месяцу."""
        return Expense.objects.filter(
            user=user,
            category=category,
            date__year=month.year,
            date__month=month.month,
        ).select_related('user', 'category')
