"""Django репозиторий для Planning модели."""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.users.models import User


class PlanningRepository:
    """Репозиторий для работы с Planning моделью."""

    def get_by_id(self, planning_id: int) -> Planning:
        """Получить planning по ID."""
        return Planning.objects.get(pk=planning_id)

    def get_by_user(self, user: User) -> QuerySet[Planning]:
        """Получить все plannings пользователя."""
        return Planning.objects.for_user(user)

    def get_by_user_with_related(self, user: User) -> QuerySet[Planning]:
        """Получить все plannings пользователя с select_related."""
        return Planning.objects.for_user(user).with_related()

    def get_expenses_by_user(self, user: User) -> QuerySet[Planning]:
        """Получить все expense plannings пользователя."""
        return Planning.objects.for_user(user).expenses()

    def get_incomes_by_user(self, user: User) -> QuerySet[Planning]:
        """Получить все income plannings пользователя."""
        return Planning.objects.for_user(user).incomes()

    def get_by_period(
        self,
        user: User,
        start: date,
        end: date,
    ) -> QuerySet[Planning]:
        """Получить plannings пользователя за период."""
        return Planning.objects.for_user(user).for_period(start, end)

    def get_or_create_planning(
        self,
        defaults: dict[str, object] | None = None,
        **kwargs: object,
    ) -> tuple[Planning, bool]:
        """Получить или создать planning."""
        return Planning.objects.get_or_create(
            defaults=defaults or {},
            **kwargs,
        )

    def bulk_create_plannings(
        self,
        plannings: list[Planning],
    ) -> list[Planning]:
        """Создать несколько plannings."""
        return Planning.objects.bulk_create(plannings)

    def create_planning(self, **kwargs: object) -> Planning:
        """Создать новый planning."""
        return Planning.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Planning]:
        """Фильтровать plannings."""
        return Planning.objects.filter(**kwargs)
