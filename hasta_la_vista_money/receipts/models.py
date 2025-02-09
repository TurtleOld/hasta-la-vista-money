from datetime import datetime

from django.db import models
from django.utils.translation import gettext as _
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User

OPERATION_TYPES = (
    (1, _('Покупка')),
    (2, _('Возврат средств за покупку')),
    (3, _(r'Продажа\Выигрыш')),
    (4, _('Возврат выигрыша или продажи')),
)


class Seller(models.Model):
    """Модель продавца."""

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='customer_users',
    )
    name_seller = models.CharField(max_length=255)
    retail_place_address = models.CharField(
        default='Нет данных',
        blank=True,
        max_length=1000,
    )
    retail_place = models.CharField(
        default='Нет данных',
        blank=True,
        max_length=1000,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name='Date created',
    )

    def __str__(self) -> str:
        return self.name_seller


class Product(models.Model):
    """Модель продуктов."""

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

    def __str__(self):
        return self.product_name


class Receipt(models.Model):
    """Модель чека."""

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
        verbose_name='customer',
        related_name='receipt_customers',
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
        ordering = ['-receipt_date']
        indexes = [
            models.Index(fields=['-receipt_date']),
            models.Index(fields=['number_receipt']),
            models.Index(fields=['nds10']),
            models.Index(fields=['nds20']),
            models.Index(fields=['operation_type']),
            models.Index(fields=['total_sum']),
        ]

    def datetime(self) -> datetime:
        return self.receipt_date
