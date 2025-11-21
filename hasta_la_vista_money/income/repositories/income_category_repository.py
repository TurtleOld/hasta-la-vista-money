"""Django репозиторий для IncomeCategory модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.users.models import User


class IncomeCategoryRepository:
    """Репозиторий для работы с IncomeCategory моделью."""

    def get_by_id(self, category_id: int) -> IncomeCategory:
        """Получить категорию по ID."""
        return IncomeCategory.objects.get(pk=category_id)

    def get_by_user(self, user: User) -> QuerySet[IncomeCategory]:
        """Получить все категории пользователя."""
        return IncomeCategory.objects.filter(user=user)

    def get_by_user_with_related(self, user: User) -> QuerySet[IncomeCategory]:
        """Получить все категории пользователя с select_related."""
        return IncomeCategory.objects.filter(user=user).select_related(
            'user', 'parent_category'
        )

    def get_by_user_ordered(self, user: User) -> QuerySet[IncomeCategory]:
        """Получить все категории пользователя, отсортированные."""
        return (
            IncomeCategory.objects.filter(user=user)
            .select_related('user', 'parent_category')
            .order_by('parent_category_id')
        )

    def create_category(self, **kwargs: object) -> IncomeCategory:
        """Создать новую категорию."""
        return IncomeCategory.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[IncomeCategory]:
        """Фильтровать категории."""
        return IncomeCategory.objects.filter(**kwargs)
