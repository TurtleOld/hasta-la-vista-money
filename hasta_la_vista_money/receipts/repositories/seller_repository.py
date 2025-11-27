"""Django репозиторий для Seller модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.receipts.models import Seller
from hasta_la_vista_money.users.models import User


class SellerRepository:
    """Репозиторий для работы с Seller моделью."""

    def update_or_create_seller(
        self,
        user: User,
        name_seller: str,
        defaults: dict[str, object] | None = None,
    ) -> Seller:
        """Создать или обновить продавца."""
        seller, _ = Seller.objects.update_or_create(
            user=user,
            name_seller=name_seller,
            defaults=defaults or {},
        )
        return seller

    def get_by_user(self, user: User) -> QuerySet[Seller]:
        """Получить всех продавцов пользователя."""
        return Seller.objects.for_user(user)  # type: ignore[attr-defined]

    def get_by_users(self, users: list[User]) -> QuerySet[Seller]:
        """Получить всех продавцов для списка пользователей."""
        return Seller.objects.for_users(users)  # type: ignore[attr-defined]

    def unique_by_name_for_user(self, user: User) -> QuerySet[Seller]:
        """Получить уникальных продавцов по имени для пользователя."""
        return Seller.objects.unique_by_name_for_user(user)  # type: ignore[attr-defined]

    def unique_by_name_for_users(self, users: list[User]) -> QuerySet[Seller]:
        """Получить уникальных продавцов по имени для списка пользователей."""
        return Seller.objects.unique_by_name_for_users(users)  # type: ignore[attr-defined]

    def filter(self, **kwargs: object) -> QuerySet[Seller]:
        """Фильтровать продавцов."""
        return Seller.objects.filter(**kwargs)
