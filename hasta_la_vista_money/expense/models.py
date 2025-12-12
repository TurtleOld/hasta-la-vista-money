"""Django models for expense management.

This module contains models for expenses and expense categories,
including relationships with users, accounts, and hierarchical categories.
"""

from typing import ClassVar

from django.db import models

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class ExpenseCategory(models.Model):
    """Model representing an expense category.

    Categories can be hierarchical with parent-child relationships.
    Each category belongs to a specific user and has a unique name
    within that user's categories.

    Attributes:
        user: Foreign key to the User who owns this category.
        name: Name of the category (max 250 characters).
        parent_category: Optional parent category for hierarchical structure.
        created_at: Timestamp when the category was created.
    """

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
        ordering: ClassVar[list[str]] = ['name']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['name']),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=['user', 'name'],
                name='unique_user_category_expense',
            ),
        ]

    def __str__(self) -> str:
        """Return string representation of the category.

        Returns:
            str: The category name.
        """
        return str(self.name)


class Expense(models.Model):
    """Model representing a financial expense.

    An expense records a monetary transaction with a date, amount,
    associated account, category, and user. Expenses are used to track
    spending and are linked to financial accounts for balance tracking.

    Attributes:
        date: Date and time when the expense occurred.
        amount: Decimal amount of the expense.
        created_at: Timestamp when the expense was created.
        user: Foreign key to the User who owns this expense.
        account: Foreign key to the Account used for this expense.
        category: Foreign key to the ExpenseCategory for this expense.
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
        verbose_name='Date created',
    )
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
        """Return string representation of the expense.

        Returns:
            str: The category name of the expense.
        """
        return str(self.category)
