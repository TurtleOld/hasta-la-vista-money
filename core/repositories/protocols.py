"""Протоколы для репозиториев."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from django.db.models import Model, QuerySet

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
    from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
    from hasta_la_vista_money.users.models import User


@runtime_checkable
class BaseRepositoryProtocol(Protocol):
    """Базовый протокол для репозиториев."""

    def get(self, **kwargs: object) -> Model: ...
    def filter(self, **kwargs: object) -> QuerySet[Model]: ...
    def create(self, **kwargs: object) -> Model: ...
    def update_or_create(
        self,
        defaults: dict[str, object] | None = None,
        **kwargs: object,
    ) -> tuple[Model, bool]: ...


@runtime_checkable
class ExpenseRepositoryProtocol(Protocol):
    """Протокол для репозитория Expense."""

    def get_by_id(self, expense_id: int) -> 'Expense': ...
    def get_by_user(self, user: 'User') -> QuerySet['Expense']: ...
    def get_by_user_and_group(
        self,
        user: 'User',
        group_id: str | None = None,
    ) -> QuerySet['Expense']: ...
    def create_expense(self, **kwargs: object) -> 'Expense': ...
    def filter(self, **kwargs: object) -> QuerySet['Expense']: ...


@runtime_checkable
class ExpenseCategoryRepositoryProtocol(Protocol):
    """Протокол для репозитория ExpenseCategory."""

    def get_by_user(self, user: 'User') -> QuerySet['ExpenseCategory']: ...
    def get_by_id(self, category_id: int) -> 'ExpenseCategory': ...
    def create_category(self, **kwargs: object) -> 'ExpenseCategory': ...
    def filter(self, **kwargs: object) -> QuerySet['ExpenseCategory']: ...


@runtime_checkable
class ReceiptRepositoryProtocol(Protocol):
    """Протокол для репозитория Receipt."""

    def get_by_id(self, receipt_id: int) -> 'Receipt': ...
    def get_by_user(self, user: 'User') -> QuerySet['Receipt']: ...
    def get_by_user_and_number(
        self,
        user: 'User',
        number_receipt: int | None,
    ) -> QuerySet['Receipt']: ...
    def create_receipt(self, **kwargs: object) -> 'Receipt': ...
    def filter(self, **kwargs: object) -> QuerySet['Receipt']: ...
    def add_product_to_receipt(
        self,
        receipt: 'Receipt',
        product: 'Product',
    ) -> None: ...


@runtime_checkable
class ProductRepositoryProtocol(Protocol):
    """Протокол для репозитория Product."""

    def create_product(self, **kwargs: object) -> 'Product': ...
    def bulk_create_products(
        self,
        products: list['Product'],
    ) -> list['Product']: ...
    def filter(self, **kwargs: object) -> QuerySet['Product']: ...


@runtime_checkable
class SellerRepositoryProtocol(Protocol):
    """Протокол для репозитория Seller."""

    def update_or_create_seller(
        self,
        user: 'User',
        name_seller: str,
        defaults: dict[str, object] | None = None,
    ) -> 'Seller': ...
    def filter(self, **kwargs: object) -> QuerySet['Seller']: ...
