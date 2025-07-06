import decimal

from django.db import models
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class Loan(models.Model):
    TYPE_LOAN = [
        ('Annuity', gettext_lazy('Аннуитетный')),
        ('Differentiated', gettext_lazy('Дифференцированный')),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='loan_users',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='loan_accounts',
    )
    date = models.DateTimeField()
    loan_amount = models.FloatField(
        max_length=constants.TWO_HUNDRED_FIFTY,
    )
    annual_interest_rate = models.DecimalField(
        max_digits=constants.TWO_HUNDRED_FIFTY,
        decimal_places=constants.TWO,
    )
    period_loan = models.IntegerField()
    type_loan = models.CharField(choices=TYPE_LOAN, default=TYPE_LOAN[0][0])

    class Meta:
        ordering = ['-id']
        indexes = [
            models.Index(fields=['-id']),
            models.Index(fields=['loan_amount']),
            models.Index(fields=['annual_interest_rate']),
            models.Index(fields=['period_loan']),
        ]

    def __str__(self):
        return _(f'Кредит №{self.pk} на сумму {self.loan_amount}')

    def get_absolute_url(self):
        return reverse('loan:delete', args=[self.pk])

    @property
    def calculate_sum_monthly_payment(self):
        from decimal import Decimal

        payments = self.payment_schedule_loans.aggregate(
            total=models.Sum('monthly_payment'),
        )['total'] or Decimal('0.00')
        return payments - Decimal(str(self.loan_amount))

    @property
    def calculate_total_amount_loan_with_interest(self):
        sum_monthly_payment = self.calculate_sum_monthly_payment
        return decimal.Decimal(self.loan_amount) + sum_monthly_payment


class PaymentMakeLoan(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='payment_make_loan_users',
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name='payment_make_loan_accounts',
    )
    date = models.DateTimeField()
    loan = models.ForeignKey(
        Loan,
        on_delete=models.CASCADE,
        related_name='loans',
    )
    amount = models.DecimalField(
        max_digits=constants.TWO_HUNDRED_FIFTY,
        decimal_places=constants.TWO,
    )


class PaymentSchedule(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='payment_schedule_users',
    )
    loan = models.ForeignKey(
        Loan,
        on_delete=models.CASCADE,
        related_name='payment_schedule_loans',
    )
    date = models.DateTimeField()
    balance = models.DecimalField(
        max_digits=constants.SIXTY,
        decimal_places=constants.TWO,
    )
    monthly_payment = models.DecimalField(
        max_digits=constants.SIXTY,
        decimal_places=constants.TWO,
    )
    interest = models.DecimalField(
        max_digits=constants.SIXTY,
        decimal_places=constants.TWO,
    )
    principal_payment = models.DecimalField(
        max_digits=constants.SIXTY,
        decimal_places=constants.TWO,
    )
