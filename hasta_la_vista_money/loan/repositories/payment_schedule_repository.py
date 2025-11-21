"""Django репозиторий для PaymentSchedule модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.loan.models import Loan, PaymentSchedule
from hasta_la_vista_money.users.models import User


class PaymentScheduleRepository:
    """Репозиторий для работы с PaymentSchedule моделью."""

    def get_by_id(self, schedule_id: int) -> PaymentSchedule:
        """Получить schedule по ID."""
        return PaymentSchedule.objects.get(pk=schedule_id)

    def get_by_user(self, user: User) -> QuerySet[PaymentSchedule]:
        """Получить все schedules пользователя."""
        return PaymentSchedule.objects.filter(user=user)

    def get_by_loan(self, loan: Loan) -> QuerySet[PaymentSchedule]:
        """Получить все schedules по loan."""
        return PaymentSchedule.objects.filter(loan=loan)

    def get_by_loans(
        self,
        loan_ids: list[int],
    ) -> QuerySet[PaymentSchedule]:
        """Получить все schedules по списку loan IDs."""
        return PaymentSchedule.objects.filter(loan_id__in=loan_ids)

    def get_by_user_with_related(self, user: User) -> QuerySet[PaymentSchedule]:
        """Получить все schedules пользователя с select_related."""
        return PaymentSchedule.objects.filter(user=user).select_related(
            'user', 'loan'
        )

    def bulk_create_schedules(
        self,
        schedules: list[PaymentSchedule],
    ) -> list[PaymentSchedule]:
        """Создать несколько schedules."""
        return PaymentSchedule.objects.bulk_create(schedules)

    def create_schedule(self, **kwargs: object) -> PaymentSchedule:
        """Создать новый schedule."""
        return PaymentSchedule.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[PaymentSchedule]:
        """Фильтровать schedules."""
        return PaymentSchedule.objects.filter(**kwargs)

    def delete_by_loan(self, loan: Loan) -> tuple[int, dict[str, int]]:
        """Удалить все schedules по loan."""
        return PaymentSchedule.objects.filter(loan=loan).delete()
