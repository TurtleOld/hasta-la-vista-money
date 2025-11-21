"""Django репозиторий для ExpenseCategory модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.users.models import User


class ExpenseCategoryRepository:
    """Репозиторий для работы с ExpenseCategory моделью."""

    def get_by_user(self, user: User) -> QuerySet[ExpenseCategory]:
        """Получить все категории пользователя."""
        return (
            user.category_expense_users.select_related('user')
            .order_by('parent_category__name', 'name')
            .all()
        )

    def get_by_id(self, category_id: int) -> ExpenseCategory:
        """Получить категорию по ID."""
        return ExpenseCategory.objects.get(pk=category_id)

    def create_category(self, **kwargs: object) -> ExpenseCategory:
        """Создать новую категорию."""
        return ExpenseCategory.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[ExpenseCategory]:
        """Фильтровать категории."""
        return ExpenseCategory.objects.filter(**kwargs)
