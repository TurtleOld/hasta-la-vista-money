"""Django репозиторий для Expense модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.expense.models import Expense
from hasta_la_vista_money.users.models import User


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
