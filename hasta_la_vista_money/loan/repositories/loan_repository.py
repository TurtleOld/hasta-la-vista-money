"""Django репозиторий для Loan модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.loan.models import Loan
from hasta_la_vista_money.users.models import User


class LoanRepository:
    """Репозиторий для работы с Loan моделью."""

    def get_by_id(self, loan_id: int) -> Loan:
        """Получить loan по ID."""
        return Loan.objects.get(pk=loan_id)

    def get_by_user(self, user: User) -> QuerySet[Loan]:
        """Получить все loans пользователя."""
        return Loan.objects.filter(user=user)

    def get_by_user_with_related(self, user: User) -> QuerySet[Loan]:
        """Получить все loans пользователя с select_related."""
        return Loan.objects.filter(user=user).select_related('user', 'account')

    def create_loan(self, **kwargs: object) -> Loan:
        """Создать новый loan."""
        return Loan.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Loan]:
        """Фильтровать loans."""
        return Loan.objects.filter(**kwargs)
