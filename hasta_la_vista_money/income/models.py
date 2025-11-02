from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.income.managers import IncomeManager
from hasta_la_vista_money.users.models import User


class IncomeCategory(models.Model):
    """
    Income category model with support for user-specific and
    hierarchical categories.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='category_income_users',
    )
    name = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
    )
    parent_category = models.ForeignKey(
        'self',
        blank=True,
        null=True,
        related_name='subcategories',
        on_delete=models.PROTECT,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ['parent_category_id']
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=['name'])]
        unique_together = ('user', 'name')

    def __str__(self) -> str:
        return str(self.name)


class Income(models.Model):
    """
    Income model representing user's income records.
    """

    date = models.DateTimeField()
    amount = models.DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=2,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name=_('Дата создания'),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='income_users',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='income_accounts',
    )
    category = models.ForeignKey(
        IncomeCategory,
        on_delete=models.PROTECT,
        related_name='income_categories',
    )
    objects = IncomeManager()

    class Meta:
        ordering: ClassVar[list[str]] = ['-date']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['-date']),
            models.Index(fields=['amount']),
            models.Index(fields=['user', 'date']),
            models.Index(fields=['user', 'category']),
            models.Index(fields=['user', 'account']),
            models.Index(fields=['date', 'amount']),
        ]

    def __str__(self) -> str:
        return str(self.category)
