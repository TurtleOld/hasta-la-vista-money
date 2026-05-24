"""Django repository for monthly budget limits."""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.budget.models import Budget
from hasta_la_vista_money.transactions.models import Category
from hasta_la_vista_money.users.models import User


class BudgetRepository:
    """Repository for Budget model operations."""

    def get_by_user(self, user: User) -> QuerySet[Budget]:
        return Budget.objects.filter(user=user).select_related('category')

    def filter(self, **kwargs: object) -> QuerySet[Budget]:
        return Budget.objects.filter(**kwargs).select_related('category')

    def get_or_create_budget(
        self,
        user: User,
        period: date,
        category: Category | None,
        defaults: dict[str, object] | None = None,
    ) -> tuple[Budget, bool]:
        return Budget.objects.get_or_create(
            user=user,
            period=period.replace(day=1),
            category=category,
            defaults=defaults or {},
        )
