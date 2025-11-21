"""Django репозиторий для Income модели."""

from datetime import date

from django.db.models import QuerySet

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
            'user', 'category', 'account'
        )

    def get_by_period(
        self,
        user: User,
        start_date: date,
        end_date: date,
    ) -> QuerySet[Income]:
        """Получить incomes пользователя за период."""
        return Income.objects.for_user(user).for_period(start_date, end_date)

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
