"""Django репозиторий для Income модели."""

from datetime import date, datetime
from typing import Any

from django.db.models import QuerySet, Sum

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.models import Income, IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeRepository:
    """Репозиторий для работы с Income моделью."""

    def get_by_id(self, income_id: int) -> Income:
        """Получить income по ID."""
        return Income.objects.get(pk=income_id)

    def get_by_user(self, user: User) -> QuerySet[Income]:
        """Получить все incomes пользователя."""
        return Income.objects.for_user(user)

    def get_by_user_with_related(self, user: User) -> QuerySet[Income]:
        """Получить все incomes пользователя с select_related."""
        return Income.objects.for_user(user).select_related(
            'user',
            'category',
            'account',
        )

    def get_by_period(
        self,
        user: User,
        start_date: date,
        end_date: date,
    ) -> QuerySet[Income]:
        """Получить incomes пользователя за период."""
        return Income.objects.for_user(user).for_period(start_date, end_date)

    def filter_by_user_and_date_range(
        self,
        user: User,
        start_date: datetime,
        end_date: datetime,
    ) -> QuerySet[Income]:
        """Фильтровать incomes пользователя за период (datetime)."""
        return Income.objects.filter(
            user=user,
            date__gte=start_date,
            date__lte=end_date,
        )

    def get_by_category(
        self,
        user: User,
        category: IncomeCategory,
    ) -> QuerySet[Income]:
        """Получить incomes пользователя по категории."""
        return Income.objects.for_user(user).for_category(category)

    def get_by_account(
        self,
        user: User,
        account_id: int,
    ) -> QuerySet[Income]:
        """Получить incomes пользователя по счёту."""
        return Income.objects.for_user(user).filter(account_id=account_id)

    def create_income(self, **kwargs: object) -> Income:
        """Создать новый income."""
        return Income.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Income]:
        """Фильтровать incomes."""
        return Income.objects.filter(**kwargs)

    def filter_with_select_related(
        self,
        *related_fields: str,
        **kwargs: object,
    ) -> QuerySet[Income]:
        """Фильтровать incomes с select_related."""
        return Income.objects.filter(**kwargs).select_related(*related_fields)

    def filter_by_account(
        self,
        account: Account,
    ) -> QuerySet[Income]:
        """Фильтровать incomes по счету."""
        return Income.objects.filter(account=account).order_by('date')

    def get_aggregated_by_date(
        self,
        user: User,
    ) -> QuerySet[Income, dict[str, Any]]:
        """Получить агрегированные incomes по датам."""
        return (
            Income.objects.filter(user=user)
            .values('date')
            .annotate(total_amount=Sum('amount'))
            .order_by('date')
        )

    def get_top_categories(
        self,
        user: User,
        year_start: datetime,
        limit: int = 10,
    ) -> QuerySet[Income, dict[str, Any]]:
        """Получить топ категорий доходов."""
        return (
            Income.objects.filter(user=user, date__gte=year_start)
            .values('category__name')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:limit]
        )

    def filter_by_user_category_and_month(
        self,
        user: User,
        category: IncomeCategory,
        month: date,
    ) -> QuerySet[Income]:
        """Фильтровать incomes по пользователю, категории и месяцу."""
        return Income.objects.filter(
            user=user,
            category=category,
            date__year=month.year,
            date__month=month.month,
        ).select_related('user', 'category')
