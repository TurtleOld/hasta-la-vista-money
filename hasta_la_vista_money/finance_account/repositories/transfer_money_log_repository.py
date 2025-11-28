"""Django репозиторий для TransferMoneyLog модели."""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.finance_account.models import TransferMoneyLog
from hasta_la_vista_money.users.models import User


class TransferMoneyLogRepository:
    """Репозиторий для работы с TransferMoneyLog моделью."""

    def get_by_id(self, log_id: int) -> TransferMoneyLog:
        """Получить log по ID."""
        return TransferMoneyLog.objects.get(pk=log_id)

    def get_by_user(self, user: User) -> QuerySet[TransferMoneyLog]:
        """Получить все logs пользователя."""
        return TransferMoneyLog.objects.filter(user=user)

    def get_by_user_with_related(
        self, user: User
    ) -> QuerySet[TransferMoneyLog]:
        """Получить все logs пользователя с select_related."""
        return TransferMoneyLog.objects.filter(user=user).select_related(
            'to_account', 'from_account', 'user'
        )

    def get_by_user_ordered(
        self,
        user: User,
        limit: int | None = None,
    ) -> QuerySet[TransferMoneyLog]:
        """Получить logs пользователя, отсортированные по дате."""
        queryset = (
            TransferMoneyLog.objects.filter(user=user)
            .select_related('to_account', 'from_account', 'user')
            .order_by('-exchange_date')
        )
        if limit:
            return queryset[:limit]
        return queryset

    def get_by_date_range(
        self,
        user: User,
        start: date,
        end: date,
    ) -> QuerySet[TransferMoneyLog]:
        """Получить logs пользователя за период."""
        return TransferMoneyLog.objects.by_user(user).by_date_range(start, end)

    def create_log(self, **kwargs: object) -> TransferMoneyLog:
        """Создать новый log."""
        return TransferMoneyLog.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[TransferMoneyLog]:
        """Фильтровать logs."""
        return TransferMoneyLog.objects.filter(**kwargs)
