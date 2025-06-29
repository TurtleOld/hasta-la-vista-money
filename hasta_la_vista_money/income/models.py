from django.db import models
from django.utils.translation import gettext_lazy as _
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.models import CommonIncomeExpense
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class IncomeCategory(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='category_income_users',
    )
    name = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        unique=True,
    )
    parent_category = models.ForeignKey(
        'self',
        blank=True,
        null=True,
        related_name='subcategories',
        on_delete=models.PROTECT,
    )

    class Meta:
        ordering = ['parent_category_id']
        indexes = [models.Index(fields=['name'])]

    def __str__(self):
        return self.name


class Income(CommonIncomeExpense):
    """Модель доходов."""

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
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name=_('Дата создания'),
    )

    class Meta(CommonIncomeExpense.Meta):
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['user', 'category']),
            models.Index(fields=['user', 'account']),
            models.Index(fields=['date', 'amount']),
        ]

    def __str__(self):
        return str(self.category)
