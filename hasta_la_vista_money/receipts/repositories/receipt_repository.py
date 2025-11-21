"""Django репозиторий для Receipt модели."""

from django.db.models import QuerySet

from hasta_la_vista_money.receipts.models import Receipt
from hasta_la_vista_money.users.models import User


class ReceiptRepository:
    """Репозиторий для работы с Receipt моделью."""

    def get_by_id(self, receipt_id: int) -> Receipt:
        """Получить receipt по ID."""
        return Receipt.objects.get(pk=receipt_id)

    def get_by_user(self, user: User) -> QuerySet[Receipt]:
        """Получить все receipts пользователя."""
        return Receipt.objects.for_user(user)

    def get_by_users(self, users: list[User]) -> QuerySet[Receipt]:
        """Получить все receipts для списка пользователей."""
        return Receipt.objects.for_users(users)

    def get_by_user_with_related(self, user: User) -> QuerySet[Receipt]:
        """Получить все receipts пользователя с select_related."""
        return Receipt.objects.for_user(user).with_related()

    def get_by_users_with_related(
        self,
        users: list[User],
    ) -> QuerySet[Receipt]:
        """Получить все receipts для списка пользователей с select_related."""
        return Receipt.objects.for_users(users).with_related()

    def get_by_user_and_number(
        self,
        user: User,
        number_receipt: int | None,
    ) -> QuerySet[Receipt]:
        """Получить receipts пользователя по номеру чека."""
        return Receipt.objects.for_user_and_number(user, number_receipt)

    def add_product_to_receipt(
        self,
        receipt: Receipt,
        product: 'Product',
    ) -> None:
        """Добавить продукт к receipt."""
        receipt.product.add(product)

    def create_receipt(self, **kwargs: object) -> Receipt:
        """Создать новый receipt."""
        return Receipt.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Receipt]:
        """Фильтровать receipts."""
        return Receipt.objects.filter(**kwargs)
