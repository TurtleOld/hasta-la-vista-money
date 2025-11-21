"""Django репозиторий для PaymentMakeLoan модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.loan.models import Loan, PaymentMakeLoan
from hasta_la_vista_money.users.models import User


class PaymentMakeLoanRepository:
    """Репозиторий для работы с PaymentMakeLoan моделью."""

    def get_by_id(self, payment_id: int) -> PaymentMakeLoan:
        """Получить payment по ID."""
        return PaymentMakeLoan.objects.get(pk=payment_id)

    def get_by_user(self, user: User) -> QuerySet[PaymentMakeLoan]:
        """Получить все payments пользователя."""
        return PaymentMakeLoan.objects.filter(user=user)

    def get_by_loan(self, loan: Loan) -> QuerySet[PaymentMakeLoan]:
        """Получить все payments по loan."""
        return PaymentMakeLoan.objects.filter(loan=loan)

    def get_by_user_with_related(self, user: User) -> QuerySet[PaymentMakeLoan]:
        """Получить все payments пользователя с select_related."""
        return PaymentMakeLoan.objects.filter(user=user).select_related(
            'user', 'account', 'loan'
        )

    def create_payment(self, **kwargs: object) -> PaymentMakeLoan:
        """Создать новый payment."""
        return PaymentMakeLoan.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[PaymentMakeLoan]:
        """Фильтровать payments."""
        return PaymentMakeLoan.objects.filter(**kwargs)
