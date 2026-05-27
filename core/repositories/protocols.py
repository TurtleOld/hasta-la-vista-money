"""Repository protocols for data access layer.

This module defines Protocol interfaces for repositories, ensuring
consistent data access patterns across the application.
"""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from django.db.models import QuerySet

if TYPE_CHECKING:
    from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
    from hasta_la_vista_money.transactions.models import Category, Transaction
    from hasta_la_vista_money.users.models import User


@runtime_checkable
class TransactionRepositoryProtocol(Protocol):
    """Protocol for Transaction repository operations."""

    def get_by_id(self, transaction_id: int) -> 'Transaction':
        """Get transaction by ID.

        Args:
            transaction_id: Transaction ID.

        Returns:
            Transaction instance.

        Raises:
            Transaction.DoesNotExist: If transaction not found.
        """
        ...

    def get_by_user(self, user: 'User') -> QuerySet['Transaction']:
        """Get transactions for a user.

        Args:
            user: User instance.

        Returns:
            QuerySet of transactions.
        """
        ...

    def get_by_user_and_group(
        self,
        user: 'User',
        group_id: str | None = None,
    ) -> QuerySet['Transaction']:
        """Get transactions for user or group.

        Args:
            user: User instance.
            group_id: Optional group ID.

        Returns:
            QuerySet of transactions.
        """
        ...

    def create_transaction(self, **kwargs: object) -> 'Transaction':
        """Create a new transaction.

        Args:
            **kwargs: Transaction field values.

        Returns:
            Created Transaction instance.
        """
        ...

    def filter(self, **kwargs: object) -> QuerySet['Transaction']:
        """Filter transactions.

        Args:
            **kwargs: Filter criteria.

        Returns:
            QuerySet of matching transactions.
        """
        ...


@runtime_checkable
class CategoryRepositoryProtocol(Protocol):
    """Protocol for Category repository operations."""

    def get_by_user(self, user: 'User') -> QuerySet['Category']:
        """Get categories for a user.

        Args:
            user: User instance.

        Returns:
            QuerySet of categories.
        """
        ...

    def get_by_id(self, category_id: int) -> 'Category':
        """Get category by ID.

        Args:
            category_id: Category ID.

        Returns:
            Category instance.

        Raises:
            Category.DoesNotExist: If category not found.
        """
        ...

    def create_category(self, **kwargs: object) -> 'Category':
        """Create a new category.

        Args:
            **kwargs: Category field values.

        Returns:
            Created Category instance.
        """
        ...

    def filter(self, **kwargs: object) -> QuerySet['Category']:
        """Filter categories.

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
