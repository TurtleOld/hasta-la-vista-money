"""Django models for receipt management.

This module contains models for receipts, sellers, and products,
including relationships with users and accounts.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import ClassVar

from django.contrib.postgres.indexes import GinIndex, OpClass
from django.contrib.postgres.search import SearchVector
from django.db import models
from django.db.models import Min
from django.db.models.functions import Lower
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from pgvector.django import HnswIndex, VectorField

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
    inn = models.CharField(
        max_length=12,
        blank=True,
        null=True,
        db_index=True,
        verbose_name='ИНН',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name='Date created',
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(
                SearchVector('name_seller', config='russian'),
                name='receipts_seller_search_gin',
            ),
        ]

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


class ProductCategory(models.Model):
    """A flat product category directory belonging to one user."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='product_categories',
    )
    name = models.CharField(max_length=constants.TWO_HUNDRED_FIFTY)
    normalized_name = models.CharField(max_length=constants.TWO_HUNDRED_FIFTY)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['user', 'normalized_name'],
                name='unique_user_normalized_product_category',
            ),
        ]
        ordering: ClassVar[list[str]] = ['name']

    def __str__(self) -> str:
        return self.name


class ProductNameCategoryMapping(models.Model):
    """A pinned product-name-to-category mapping for one user.

    Wins over every other categorization stage: once a name is pinned here,
    subsequent occurrences of the same normalized name always get this
    category and the writing/semantic/external-model stages are skipped.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='product_name_category_mappings',
    )
    normalized_product_name = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
    )
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.CASCADE,
        related_name='name_mappings',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['user', 'normalized_product_name'],
                name='unique_user_normalized_product_name_mapping',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.normalized_product_name} -> {self.category.name}'


class ProductCategorySource(models.TextChoices):
    """How a product row received its category."""

    MIGRATED = 'migrated', _('Перенесено')
    NAME_MATCH = 'name_match', _('Закреплённое сопоставление')
    WRITING_MATCH = 'writing_match', _('Подбор по написанию')
    SEMANTIC_MATCH = 'semantic_match', _('Подбор по смыслу')
    EXTERNAL_MODEL = 'external_model', _('Внешняя модель')
    MANUAL = 'manual', _('Поставлено человеком')


class CategoryMergeProposalStatus(models.TextChoices):
    """Lifecycle states for a twin-category merge proposal."""

    PENDING = 'pending', _('Ожидает решения')
    MERGED = 'merged', _('Объединено')
    KEPT = 'kept', _('Оставлено')


class CategoryMergeProposal(models.Model):
    """A pair of categories that may denote the same kind of purchase."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='category_merge_proposals',
    )
    category_a = models.ForeignKey(
        ProductCategory,
        null=True,
        on_delete=models.SET_NULL,
        related_name='merge_proposals_as_a',
    )
    category_b = models.ForeignKey(
        ProductCategory,
        null=True,
        on_delete=models.SET_NULL,
        related_name='merge_proposals_as_b',
    )
    status = models.CharField(
        choices=CategoryMergeProposalStatus.choices,
        default=CategoryMergeProposalStatus.PENDING,
        max_length=constants.TWENTY,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ['-created_at']
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['user', 'category_a', 'category_b'],
                name='uniq_user_category_merge_pair',
            ),
        ]

    def __str__(self) -> str:
        return (
            f'{self.category_a} ↔ {self.category_b} '
            f'({self.get_status_display()})'
        )


class Product(models.Model):
    """Model representing a product from a receipt.

    Stores information about individual products purchased,
    including name, price, quantity, and tax information.

    Attributes:
        user: Foreign key to the User who owns this product.
        product_name: Name of the product.
        category: Product category directory entry.
        category_source: How the category was assigned.
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
    category = models.ForeignKey(
        ProductCategory,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='products',
    )
    category_source = models.CharField(
        choices=ProductCategorySource.choices,
        default=ProductCategorySource.WRITING_MATCH,
        max_length=constants.TWENTY,
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
    name_embedding = VectorField(
        dimensions=constants.PRODUCT_NAME_EMBEDDING_DIMENSIONS,
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(
                SearchVector(
                    'product_name',
                    config='russian',
                ),
                name='receipts_product_search_gin',
            ),
            GinIndex(
                OpClass(Lower('product_name'), name='gin_trgm_ops'),
                name='receipts_product_name_trgm_gin',
            ),
            HnswIndex(
                name='receipts_product_embedding_hnsw',
                fields=['name_embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ]

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
        ).prefetch_related(
            models.Prefetch(
                'product',
                queryset=Product.objects.select_related('category'),
            ),
        )

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
        nds20: VAT amount at 22% rate.
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
    number_receipt = models.BigIntegerField(default=None, null=True)
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
    adjustment = models.DecimalField(
        default=0,
        max_digits=10,
        decimal_places=2,
    )
    requires_attention = models.BooleanField(default=False)
    attention_reason = models.TextField(blank=True, default='')
    fiscal_key = models.CharField(
        max_length=255,
        null=True,
        blank=True,
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
        on_delete=models.SET_NULL,
        verbose_name='seller',
        related_name='receipt_sellers',
        null=True,
        blank=True,
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
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['user', 'fiscal_key'],
                condition=models.Q(fiscal_key__isnull=False),
                name='uniq_receipt_user_fiscal_key',
            ),
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


class ReceiptProcessingStatus(models.TextChoices):
    """Lifecycle states for automatic receipt processing."""

    PROCESSING = 'processing', _('В обработке')
    COMPLETED = 'completed', _('Проведён')
    FAILED = 'failed', _('Ошибка обработки')
    DUPLICATE = 'duplicate', _('Повторный чек')


class ReceiptProcessingLog(models.Model):
    """Audit log for a receipt processing attempt, without receipt payload."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='receipt_processing_logs',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='receipt_processing_logs',
    )
    status = models.CharField(
        max_length=20,
        choices=ReceiptProcessingStatus.choices,
        default=ReceiptProcessingStatus.PROCESSING,
    )
    image_file = models.FileField(
        upload_to='receipt_processing_logs/',
        null=True,
        blank=True,
    )
    qr_raw = models.CharField(max_length=1024, blank=True, default='')
    image_hash = models.CharField(max_length=64, blank=True, default='')
    fiscal_key = models.CharField(max_length=255, null=True, blank=True)
    is_duplicate = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default='')
    task_id = models.CharField(max_length=64, blank=True, default='')
    receipt = models.OneToOneField(
        Receipt,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='processing_log',
    )
    processing_started_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar[list[str]] = ['-created_at']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['user', 'image_hash']),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['user', 'fiscal_key'],
                condition=models.Q(
                    fiscal_key__isnull=False,
                    status=ReceiptProcessingStatus.PROCESSING,
                ),
                name='uniq_active_processing_log_user_fiscal_key',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.get_status_display()} — {self.created_at:%d.%m.%Y %H:%M}'


class ReceiptImageHash(models.Model):
    """Persistent record of an image hash for a saved receipt.

    Lets the upload flow detect duplicate uploads even after the source
    file has been removed from disk on successful conversion.

    Attributes:
        user: Owner of the receipt.
        receipt: The saved receipt this hash belongs to.
        image_hash: SHA-256 hex digest of the original uploaded image.
        created_at: Timestamp the record was stored.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='receipt_image_hashes',
    )
    receipt = models.OneToOneField(
        Receipt,
        on_delete=models.CASCADE,
        related_name='image_hash_record',
    )
    image_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['user', 'image_hash'],
                name='uniq_user_image_hash',
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['user', 'image_hash']),
        ]
        verbose_name = _('Хеш изображения чека')
        verbose_name_plural = _('Хеши изображений чеков')

    def __str__(self) -> str:
        return f'{self.image_hash} → receipt #{self.receipt_id}'
