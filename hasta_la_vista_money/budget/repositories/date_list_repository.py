"""Django репозиторий для DateList модели."""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.budget.models import DateList
from hasta_la_vista_money.users.models import User


class DateListRepository:
    """Репозиторий для работы с DateList моделью."""

    def get_by_id(self, date_list_id: int) -> DateList:
        """Получить date_list по ID."""
        return DateList.objects.get(pk=date_list_id)

    def get_by_user(self, user: User) -> QuerySet[DateList]:
        """Получить все date_lists пользователя."""
        return DateList.objects.for_user(user)

    def get_by_user_ordered(self, user: User) -> QuerySet[DateList]:
        """Получить все date_lists пользователя, отсортированные по дате."""
        return DateList.objects.for_user(user).order_by('date')

    def get_by_date(self, target_date: date) -> QuerySet[DateList]:
        """Получить date_lists по дате."""
        return DateList.objects.for_date(target_date)

    def get_by_user_and_date(
        self,
        user: User,
        target_date: date,
    ) -> QuerySet[DateList]:
        """Получить date_lists пользователя по дате."""
        return DateList.objects.for_user(user).for_date(target_date)

    def get_latest_by_user(self, user: User) -> DateList | None:
        """Получить последний date_list пользователя."""
        return DateList.objects.for_user(user).order_by('-date').first()

    def create_date_list(self, **kwargs: object) -> DateList:
        """Создать новый date_list."""
        return DateList.objects.create(**kwargs)

    def bulk_create_date_lists(
        self,
        date_lists: list[DateList],
    ) -> list[DateList]:
        """Создать несколько date_lists."""
        return DateList.objects.bulk_create(date_lists)

    def filter(self, **kwargs: object) -> QuerySet[DateList]:
        """Фильтровать date_lists."""
        return DateList.objects.filter(**kwargs)
