"""Repository protocols for data access layer.

This module defines Protocol interfaces for repositories, ensuring
consistent data access patterns across the application.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from django.db.models import Model, QuerySet

if TYPE_CHECKING:
    from hasta_la_vista_money.expense.models import Expense, ExpenseCategory
    from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
    from hasta_la_vista_money.users.models import User


@runtime_checkable
class BaseRepositoryProtocol(Protocol):
    """Base protocol for repositories.

    Defines common CRUD operations for all repositories.
    """

    def get(self, **kwargs: object) -> Model:
        """Get a single model instance.

        Args:
            **kwargs: Filter criteria.

        Returns:
            Model instance.

        Raises:
            Model.DoesNotExist: If instance not found.
        """
        ...

    def filter(self, **kwargs: object) -> QuerySet[Model]:
        """Filter model instances.

        Args:
            **kwargs: Filter criteria.

        Returns:
            QuerySet of matching instances.
        """
        ...

    def create(self, **kwargs: object) -> Model:
        """Create a new model instance.

        Args:
            **kwargs: Model field values.

        Returns:
            Created Model instance.
        """
        ...

    def update_or_create(
        self,
        defaults: dict[str, object] | None = None,
        **kwargs: object,
    ) -> tuple[Model, bool]:
        """Update or create a model instance.

        Args:
            defaults: Values to update if instance exists.
            **kwargs: Lookup criteria.

        Returns:
            Tuple of (instance, created) where created is True if new.
        """
        ...


@runtime_checkable
class ExpenseRepositoryProtocol(Protocol):
    """Protocol for Expense repository operations."""

    def get_by_id(self, expense_id: int) -> 'Expense':
        """Get expense by ID.

        Args:
            expense_id: Expense ID.

        Returns:
            Expense instance.

        Raises:
            Expense.DoesNotExist: If expense not found.
        """
        ...

    def get_by_user(self, user: 'User') -> QuerySet['Expense']:
        """Get expenses for a user.

        Args:
            user: User instance.

        Returns:
            QuerySet of expenses.
        """
        ...

    def get_by_user_and_group(
        self,
        user: 'User',
        group_id: str | None = None,
    ) -> QuerySet['Expense']:
        """Get expenses for user or group.

        Args:
            user: User instance.
            group_id: Optional group ID.

        Returns:
            QuerySet of expenses.
        """
        ...

    def create_expense(self, **kwargs: object) -> 'Expense':
        """Create a new expense.

        Args:
            **kwargs: Expense field values.

        Returns:
            Created Expense instance.
        """
        ...

    def filter(self, **kwargs: object) -> QuerySet['Expense']:
        """Filter expenses.

        Args:
            **kwargs: Filter criteria.

        Returns:
            QuerySet of matching expenses.
        """
        ...


@runtime_checkable
class ExpenseCategoryRepositoryProtocol(Protocol):
    """Protocol for ExpenseCategory repository operations."""

    def get_by_user(self, user: 'User') -> QuerySet['ExpenseCategory']:
        """Get expense categories for a user.

        Args:
            user: User instance.

        Returns:
            QuerySet of expense categories.
        """
        ...

    def get_by_id(self, category_id: int) -> 'ExpenseCategory':
        """Get expense category by ID.

        Args:
            category_id: Category ID.

        Returns:
            ExpenseCategory instance.

        Raises:
            ExpenseCategory.DoesNotExist: If category not found.
        """
        ...

    def create_category(self, **kwargs: object) -> 'ExpenseCategory':
        """Create a new expense category.

        Args:
            **kwargs: Category field values.

        Returns:
            Created ExpenseCategory instance.
        """
        ...

    def filter(self, **kwargs: object) -> QuerySet['ExpenseCategory']:
        """Filter expense categories.

        Args:
            **kwargs: Filter criteria.

        Returns:
            QuerySet of matching categories.
        """
        ...


@runtime_checkable
class ReceiptRepositoryProtocol(Protocol):
    """Protocol for Receipt repository operations."""

    def get_by_id(self, receipt_id: int) -> 'Receipt':
        """Get receipt by ID.

        Args:
            receipt_id: Receipt ID.

        Returns:
            Receipt instance.

        Raises:
            Receipt.DoesNotExist: If receipt not found.
        """
        ...

    def get_by_user(self, user: 'User') -> QuerySet['Receipt']:
        """Get receipts for a user.

        Args:
            user: User instance.

        Returns:
            QuerySet of receipts.
        """
        ...

    def get_by_user_and_number(
        self,
        user: 'User',
        number_receipt: int | None,
    ) -> QuerySet['Receipt']:
        """Get receipts by user and receipt number.

        Args:
            user: User instance.
            number_receipt: Receipt number.

        Returns:
            QuerySet of matching receipts.
        """
        ...

    def create_receipt(self, **kwargs: object) -> 'Receipt':
        """Create a new receipt.

        Args:
            **kwargs: Receipt field values.

        Returns:
            Created Receipt instance.
        """
        ...

    def filter(self, **kwargs: object) -> QuerySet['Receipt']:
        """Filter receipts.

        Args:
            **kwargs: Filter criteria.

        Returns:
            QuerySet of matching receipts.
        """
        ...

    def add_product_to_receipt(
        self,
        receipt: 'Receipt',
        product: 'Product',
    ) -> None:
        """Add product to receipt.

        Args:
            receipt: Receipt instance.
            product: Product instance.
        """
        ...


@runtime_checkable
class ProductRepositoryProtocol(Protocol):
    """Protocol for Product repository operations."""

    def create_product(self, **kwargs: object) -> 'Product':
        """Create a new product.

        Args:
            **kwargs: Product field values.

        Returns:
            Created Product instance.
        """
        ...

    def bulk_create_products(
        self,
        products: list['Product'],
    ) -> list['Product']:
        """Bulk create products.

        Args:
            products: List of Product instances to create.

        Returns:
            List of created Product instances.
        """
        ...

    def filter(self, **kwargs: object) -> QuerySet['Product']:
        """Filter products.

        Args:
            **kwargs: Filter criteria.

        Returns:
            QuerySet of matching products.
        """
        ...


@runtime_checkable
class SellerRepositoryProtocol(Protocol):
    """Protocol for Seller repository operations."""

    def update_or_create_seller(
        self,
        user: 'User',
        name_seller: str,
        defaults: dict[str, object] | None = None,
    ) -> 'Seller':
        """Update or create a seller.

        Args:
            user: User owning the seller.
            name_seller: Seller name.
            defaults: Values to update if seller exists.

        Returns:
            Seller instance (created or updated).
        """
        ...

    def filter(self, **kwargs: object) -> QuerySet['Seller']:
        """Filter sellers.

        Args:
            **kwargs: Filter criteria.

        Returns:
            QuerySet of matching sellers.
        """
        ...
