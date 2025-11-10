from collections.abc import Iterable
from datetime import datetime
from typing import ClassVar

from django.db import models
from django.db.models import Min
from django.urls import reverse_lazy
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
    def get_queryset(self) -> 'SellerQuerySet':
        return SellerQuerySet(self.model, using=self._db)

    def for_user(self, user: User) -> 'SellerQuerySet':
        return self.get_queryset().for_user(user)

    def for_users(self, users: Iterable[User]) -> 'SellerQuerySet':
        return self.get_queryset().for_users(users)

    def unique_by_name_for_users(
        self,
        users: Iterable[User],
    ) -> 'SellerQuerySet':
        return self.get_queryset().unique_by_name_for_users(users)

    def unique_by_name_for_user(self, user: User) -> 'SellerQuerySet':
        return self.get_queryset().unique_by_name_for_user(user)


class Seller(models.Model):
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
        return str(self.name_seller)

    objects = SellerManager()


class SellerQuerySet(models.QuerySet[Seller]):
    def for_user(self, user: User) -> 'SellerQuerySet':
        return self.filter(user=user)

    def for_users(self, users: Iterable[User]) -> 'SellerQuerySet':
        return self.filter(user__in=users)

    def unique_by_name_for_users(
        self,
        users: Iterable[User],
    ) -> 'SellerQuerySet':
        seller_ids = (
            self.for_users(users)
            .values('name_seller')
            .annotate(min_id=Min('id'))
            .values('min_id')
        )
        return self.filter(pk__in=seller_ids).select_related('user')

    def unique_by_name_for_user(self, user: User) -> 'SellerQuerySet':
        seller_ids = (
            self.for_user(user)
            .values('name_seller')
            .annotate(min_id=Min('id'))
            .values('min_id')
        )
        return self.filter(pk__in=seller_ids).select_related('user')


class Product(models.Model):
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
        return self.product_name


class ReceiptQuerySet(models.QuerySet['Receipt']):
    def with_related(self) -> 'ReceiptQuerySet':
        return self.select_related(
            'user',
            'account',
            'seller',
        ).prefetch_related('product')

    def for_user(self, user: User) -> 'ReceiptQuerySet':
        return self.filter(user=user)

    def for_users(self, users: Iterable[User]) -> 'ReceiptQuerySet':
        return self.filter(user__in=users)

    def for_user_and_number(
        self,
        user: User,
        number_receipt: int | None,
    ) -> 'ReceiptQuerySet':
        return self.for_user(user).filter(number_receipt=number_receipt)


class ReceiptManager(models.Manager['Receipt']):
    def get_queryset(self) -> 'ReceiptQuerySet':
        return ReceiptQuerySet(self.model, using=self._db)

    def with_related(self) -> 'ReceiptQuerySet':
        return self.get_queryset().with_related()

    def for_user(self, user: User) -> 'ReceiptQuerySet':
        return self.get_queryset().filter(user=user)

    def for_users(self, users: Iterable[User]) -> 'ReceiptQuerySet':
        return self.get_queryset().filter(user__in=users)

    def for_user_and_number(
        self,
        user: User,
        number_receipt: int | None,
    ) -> 'ReceiptQuerySet':
        return self.get_queryset().filter(
            user=user,
            number_receipt=number_receipt,
        )


class Receipt(models.Model):
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
        return self.receipt_date

    objects = ReceiptManager()

    def get_absolute_url(self) -> str:
        return reverse_lazy('receipts:update', args=[self.pk])
