from django.db import models
from hasta_la_vista_money import constants
from hasta_la_vista_money.commonlogic.models import CommonIncomeExpense
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class ExpenseCategory(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='category_expense_users',
    )
    name = models.CharField(
        max_length=constants.TWO_HUNDRED_FIFTY,
        unique=False,
    )
    parent_category = models.ForeignKey(
        'self',
        blank=True,
        null=True,
        related_name='subcategories',
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name='Date created',
    )

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_user_category_expense"
            )
        ]

    def __str__(self):
        return str(self.name)


class Expense(CommonIncomeExpense):
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='expense_users',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='expense_accounts',
    )
    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name='expense_categories',
    )

    class Meta(CommonIncomeExpense.Meta):
        indexes = CommonIncomeExpense.Meta.indexes + [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['user', 'category']),
            models.Index(fields=['user', 'account']),
            models.Index(fields=['date', 'amount']),
        ]

    def __str__(self):
        return str(self.category)
