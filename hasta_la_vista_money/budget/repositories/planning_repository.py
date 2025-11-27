"""Django репозиторий для Planning модели."""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.budget.models import Planning
from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.users.models import User


class PlanningRepository:
    """Репозиторий для работы с Planning моделью."""

    def get_by_id(self, planning_id: int) -> Planning:
        """Получить planning по ID."""
        return Planning.objects.get(pk=planning_id)

    def get_by_user(self, user: User) -> QuerySet[Planning]:
        """Получить все plannings пользователя."""
        return Planning.objects.for_user(user)  # type: ignore[attr-defined]

    def get_by_user_with_related(self, user: User) -> QuerySet[Planning]:
        """Получить все plannings пользователя с select_related."""
        return Planning.objects.for_user(user).with_related()  # type: ignore[attr-defined]

    def get_expenses_by_user(self, user: User) -> QuerySet[Planning]:
        """Получить все expense plannings пользователя."""
        return Planning.objects.for_user(user).expenses()  # type: ignore[attr-defined]

    def get_incomes_by_user(self, user: User) -> QuerySet[Planning]:
        """Получить все income plannings пользователя."""
        return Planning.objects.for_user(user).incomes()  # type: ignore[attr-defined]

    def get_by_period(
        self,
        user: User,
        start: date,
        end: date,
    ) -> QuerySet[Planning]:
        """Получить plannings пользователя за период."""
        return Planning.objects.for_user(user).for_period(start, end)  # type: ignore[attr-defined]

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

    def filter_by_user_date_and_type(
        self,
        user: User,
        month: date,
        planning_type: str,
    ) -> QuerySet[Planning]:
        """Фильтровать planning по пользователю, дате и типу."""
        return Planning.objects.filter(
            user=user,
            date=month,
            planning_type=planning_type,
        ).select_related('user', 'category_expense', 'category_income')

    def filter_by_user_category_and_month(
        self,
        user: User,
        category: ExpenseCategory | IncomeCategory,
        month: date,
        planning_type: str,
    ) -> Planning | None:
        """Получить planning по пользователю, категории и месяцу."""
        qs = self.filter_by_user_date_and_type(user, month, planning_type)
        if planning_type == 'expense' and isinstance(category, ExpenseCategory):
            return qs.filter(category_expense=category).first()
        if planning_type == 'income' and isinstance(category, IncomeCategory):
            return qs.filter(category_income=category).first()
        return None
