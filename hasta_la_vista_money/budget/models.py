from django.db import models
from hasta_la_vista_money.users.models import User
from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.income.models import IncomeCategory
from datetime import date


class DateList(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='budget_date_list_users',
    )
    date = models.DateField(default=date.today)
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name='Date created',
    )


class Planning(models.Model):
    TYPE_CHOICES = (
        ('expense', 'Расход'),
        ('income', 'Доход'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    category_expense = models.ForeignKey(
        ExpenseCategory, null=True, blank=True, on_delete=models.CASCADE
    )
    category_income = models.ForeignKey(
        IncomeCategory, null=True, blank=True, on_delete=models.CASCADE
    )
    date = models.DateField(default=date.today)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='expense')
    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True,
        verbose_name='Date created',
    )

    class Meta:
        unique_together = (
            'user',
            'category_expense',
            'category_income',
            'date',
            'type',
        )
