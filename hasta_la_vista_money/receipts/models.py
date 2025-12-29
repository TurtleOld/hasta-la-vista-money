"""Django models for receipt management.

This module contains models for receipts, sellers, and products,
including relationships with users and accounts.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, ClassVar

from django.db import models
from django.db.models import Min
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User

OPERATION_TYPES = (
    (1, _('Покупка')),
    (2, _('Возврат средств за покупку')),
    (3, _(r'Продажа\Выигрыш')),
    (4, _('Возврат выигрыша или продажи')),
)


class SellerManager(models.Manager['Seller']):
    """Custom manager for Seller model with user filtering methods."""

    def get_queryset(self) -> 'SellerQuerySet':
        return SellerQuerySet(self.model, using=self._db)

    def for_user(self, user: User) -> 'SellerQuerySet':
        """Get sellers for a specific user.

        Args:
            user: User instance to filter by.

        Returns:
            SellerQuerySet: QuerySet filtered by user.
        """
        return self.get_queryset().for_user(user)

    def for_users(self, users: Iterable[User]) -> 'SellerQuerySet':
        """Get sellers for multiple users.

        Args:
            users: Iterable of User instances to filter by.

        Returns:
            SellerQuerySet: QuerySet filtered by users.
        """
        return self.get_queryset().for_users(users)

    def unique_by_name_for_users(
        self,
        users: Iterable[User],
    ) -> 'SellerQuerySet':
        """Get unique sellers by name for multiple users.

        Args:
            users: Iterable of User instances to filter by.

        Returns:
            SellerQuerySet: QuerySet with unique sellers by name.
        """
        return self.get_queryset().unique_by_name_for_users(users)

    def unique_by_name_for_user(self, user: User) -> 'SellerQuerySet':
        """Get unique sellers by name for a specific user.

        Args:
            user: User instance to filter by.

        Returns:
            SellerQuerySet: QuerySet with unique sellers by name.
        """
        return self.get_queryset().unique_by_name_for_user(user)


class Seller(models.Model):
    """Model representing a seller or retail place.

    Stores information about sellers from receipts, including
    name, address, and retail place details.

    Attributes:
        user: Foreign key to the User who owns this seller.
        name_seller: Name of the seller/retail place.
        retail_place_address: Address of the retail place.
        retail_place: Name of the retail place.
        created_at: Timestamp when the seller was created.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='seller_users',
    )
    name_seller = models.CharField(max_length=255)
    retail_place_address = models.CharField(
        default='Нет данных',
        blank=True,
        null=True,
        max_length=1000,
    )
    retail_place = models.CharField(
        default='Нет данных',
        blank=True,
        null=True,
        max_length=1000,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name='Date created',
    )

    def __str__(self) -> str:
        """Return string representation of the seller.

        Returns:
            str: The seller name.
        """
        return str(self.name_seller)

    objects = SellerManager()


class SellerQuerySet(models.QuerySet[Seller]):
    """Custom QuerySet for Seller model with filtering methods."""

    def for_user(self, user: User) -> 'SellerQuerySet':
        """Filter sellers by user.

        Args:
            user: User instance to filter by.

        Returns:
            SellerQuerySet: Filtered QuerySet.
        """
        return self.filter(user=user)

    def for_users(self, users: Iterable[User]) -> 'SellerQuerySet':
        """Filter sellers by multiple users.

        Args:
            users: Iterable of User instances to filter by.

        Returns:
            SellerQuerySet: Filtered QuerySet.
        """
        return self.filter(user__in=users)

    def unique_by_name_for_users(
        self,
        users: Iterable[User],
    ) -> 'SellerQuerySet':
        """Get unique sellers by name for multiple users.

        Returns sellers with the minimum ID for each unique name
        among the specified users.

        Args:
            users: Iterable of User instances to filter by.

        Returns:
            SellerQuerySet: QuerySet with unique sellers by name.
        """
        seller_ids = (
            self.for_users(users)
            .values('name_seller')
            .annotate(min_id=Min('id'))
            .values('min_id')
        )
        return self.filter(pk__in=seller_ids).select_related('user')

    def unique_by_name_for_user(self, user: User) -> 'SellerQuerySet':
        """Get unique sellers by name for a specific user.

        Returns sellers with the minimum ID for each unique name
        for the specified user.

        Args:
            user: User instance to filter by.

        Returns:
            SellerQuerySet: QuerySet with unique sellers by name.
        """
        seller_ids = (
            self.for_user(user)
            .values('name_seller')
            .annotate(min_id=Min('id'))
            .values('min_id')
        )
        return self.filter(pk__in=seller_ids).select_related('user')


class Product(models.Model):
    """Model representing a product from a receipt.

    Stores information about individual products purchased,
    including name, price, quantity, and tax information.

    Attributes:
        user: Foreign key to the User who owns this product.
        product_name: Name of the product.
        category: Product category.
        price: Price per unit of the product.
        quantity: Quantity purchased.
        amount: Total amount for this product.
        nds_type: VAT type code.
        nds_sum: VAT amount.
        created_at: Timestamp when the product was created.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='product_users',
    )
    product_name = models.CharField(default='', max_length=1000)
    category = models.CharField(
        blank=True,
        max_length=constants.TWO_HUNDRED_FIFTY,
    )
    price = models.DecimalField(default=0, max_digits=10, decimal_places=2)
    quantity = models.DecimalField(
        default=0,
        max_digits=10,
        decimal_places=2,
        verbose_name='Количество',
    )
    amount = models.DecimalField(default=0, max_digits=10, decimal_places=2)
    nds_type = models.IntegerField(default=None, null=True, blank=True)
    nds_sum = models.DecimalField(
        default=0,
        null=True,
        max_digits=10,
        decimal_places=2,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name='Date created',
    )

    def __str__(self) -> str:
        """Return string representation of the product.

        Returns:
            str: The product name.
        """
        return self.product_name


class ReceiptQuerySet(models.QuerySet['Receipt']):
    """Custom QuerySet for Receipt model with filtering methods."""

    def with_related(self) -> 'ReceiptQuerySet':
        """Optimize queries by joining related objects.

        Returns:
            ReceiptQuerySet: QuerySet with select_related and prefetch_related
                optimizations applied.
        """
        return self.select_related(
            'user',
            'account',
            'seller',
        ).prefetch_related('product')

    def for_user(self, user: User) -> 'ReceiptQuerySet':
        """Filter receipts by user.

        Args:
            user: User instance to filter by.

        Returns:
            ReceiptQuerySet: Filtered QuerySet.
        """
        return self.filter(user=user)

    def for_users(self, users: Iterable[User]) -> 'ReceiptQuerySet':
        """Filter receipts by multiple users.

        Args:
            users: Iterable of User instances to filter by.

        Returns:
            ReceiptQuerySet: Filtered QuerySet.
        """
        return self.filter(user__in=users)

    def for_user_and_number(
        self,
        user: User,
        number_receipt: int | None,
    ) -> 'ReceiptQuerySet':
        """Filter receipts by user and receipt number.

        Args:
            user: User instance to filter by.
            number_receipt: Receipt number to filter by.

        Returns:
            ReceiptQuerySet: Filtered QuerySet.
        """
        return self.for_user(user).filter(number_receipt=number_receipt)


class ReceiptManager(models.Manager['Receipt']):
    """Custom manager for Receipt model with filtering methods."""

    def get_queryset(self) -> 'ReceiptQuerySet':
        """Get QuerySet for Receipt model.

        Returns:
            ReceiptQuerySet: Custom QuerySet instance.
        """
        return ReceiptQuerySet(self.model, using=self._db)

    def with_related(self) -> 'ReceiptQuerySet':
        """Get QuerySet with related objects optimized.

        Returns:
            ReceiptQuerySet: QuerySet with select_related and prefetch_related.
        """
        return self.get_queryset().with_related()

    def for_user(self, user: User) -> 'ReceiptQuerySet':
        """Get receipts for a specific user.

        Args:
            user: User instance to filter by.

        Returns:
            ReceiptQuerySet: Filtered QuerySet.
        """
        return self.get_queryset().filter(user=user)

    def for_users(self, users: Iterable[User]) -> 'ReceiptQuerySet':
        """Get receipts for multiple users.

        Args:
            users: Iterable of User instances to filter by.

        Returns:
            ReceiptQuerySet: Filtered QuerySet.
        """
        return self.get_queryset().filter(user__in=users)

    def for_user_and_number(
        self,
        user: User,
        number_receipt: int | None,
    ) -> 'ReceiptQuerySet':
        """Get receipts for a user by receipt number.

        Args:
            user: User instance to filter by.
            number_receipt: Receipt number to filter by.

        Returns:
            ReceiptQuerySet: Filtered QuerySet.
        """
        return self.get_queryset().filter(
            user=user,
            number_receipt=number_receipt,
        )


class Receipt(models.Model):
    """Model representing a receipt from a purchase.

    Stores information about receipts including date, seller, products,
    totals, VAT information, and operation type.

    Attributes:
        receipt_date: Date and time of the receipt.
        number_receipt: Fiscal document number.
        nds10: VAT amount at 10% rate.
        nds20: VAT amount at 20% rate.
        operation_type: Type of operation (purchase, return, etc.).
        total_sum: Total sum of the receipt.
        manual: Whether receipt was entered manually.
        created_at: Timestamp when the receipt was created.
        seller: Foreign key to the Seller.
        user: Foreign key to the User who owns this receipt.
        account: Foreign key to the Account used for this receipt.
        product: Many-to-many relationship with Product.
    """

    receipt_date = models.DateTimeField()
    number_receipt = models.IntegerField(default=None, null=True)
    nds10 = models.DecimalField(
        blank=True,
        max_digits=constants.SIXTY,
        null=True,
        decimal_places=constants.TWO,
    )
    nds20 = models.DecimalField(
        blank=True,
        max_digits=constants.SIXTY,
        null=True,
        decimal_places=constants.TWO,
    )
    operation_type = models.IntegerField(
        default=0,
        null=True,
        blank=True,
        choices=OPERATION_TYPES,
    )
    total_sum = models.DecimalField(
        default=0,
        max_digits=10,
        decimal_places=2,
    )
    manual = models.BooleanField(null=True)
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name='Date created',
    )
    seller = models.ForeignKey(
        Seller,
        on_delete=models.CASCADE,
        verbose_name='seller',
        related_name='receipt_sellers',
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='receipt_users',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='receipt_accounts',
    )
    product = models.ManyToManyField(Product, related_name='receipt_products')

    class Meta:
        ordering: ClassVar[list[str]] = ['-receipt_date']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['-receipt_date']),
            models.Index(fields=['number_receipt']),
            models.Index(fields=['nds10']),
            models.Index(fields=['nds20']),
            models.Index(fields=['operation_type']),
            models.Index(fields=['total_sum']),
        ]

    def datetime(self) -> datetime:
        """Get receipt date as datetime.

        Returns:
            datetime: Receipt date and time.
        """
        return self.receipt_date

    objects = ReceiptManager()

    def get_absolute_url(self) -> str:
        """Get absolute URL for receipt update.

        Returns:
            str: URL for updating this receipt.
        """
        return str(reverse_lazy('receipts:update', args=[self.pk]))


class PendingReceipt(models.Model):
    """Model for temporarily storing receipt data before final confirmation.

    Stores receipt data from AI recognition in JSON format,
    allowing users to review and edit before saving to Receipt model.

    Attributes:
        user: Foreign key to the User who uploaded the receipt.
        account: Foreign key to the Account used for this receipt.
        receipt_data: JSON field containing all receipt data.
        created_at: Timestamp when the pending receipt was created.
        expires_at: Timestamp when the pending receipt expires.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='pending_receipts',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='pending_receipts',
    )
    receipt_data = models.JSONField(
        verbose_name=_('Данные чека'),
        help_text=_('JSON данные чека для редактирования'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Дата создания'),
    )
    expires_at = models.DateTimeField(
        verbose_name=_('Дата истечения'),
        help_text=_('Время, после которого запись будет удалена'),
    )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Override save to set expires_at if not provided.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments.
        """
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    class Meta:
        ordering: ClassVar[list[str]] = ['-created_at']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['expires_at']),
        ]
        verbose_name = _('Временный чек')
        verbose_name_plural = _('Временные чеки')

    def __str__(self) -> str:
        """Return string representation of the pending receipt.

        Returns:
            str: Pending receipt identifier.
        """
        seller_name = self.receipt_data.get(
            'name_seller', 'Неизвестный продавец'
        )
        return f'{seller_name} - {self.created_at.strftime("%d.%m.%Y %H:%M")}'

    def get_absolute_url(self) -> str:
        """Get absolute URL for pending receipt review.

        Returns:
            str: URL for reviewing this pending receipt.
        """
        return str(reverse_lazy('receipts:review', args=[self.pk]))
