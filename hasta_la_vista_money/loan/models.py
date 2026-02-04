import decimal
from decimal import Decimal
from typing import ClassVar

from django.db import models
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User


class Loan(models.Model):
    TYPE_LOAN: ClassVar[list[tuple[str, str | Promise]]] = [
        ('Annuity', _('Аннуитетный')),
        ('Differentiated', _('Дифференцированный')),
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
    type_loan = models.CharField(
        max_length=20,
        choices=TYPE_LOAN,
        default=TYPE_LOAN[0][0],
    )

    class Meta:
        ordering: ClassVar[list[str]] = ['-id']
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=['-id']),
            models.Index(fields=['loan_amount']),
            models.Index(fields=['annual_interest_rate']),
            models.Index(fields=['period_loan']),
        ]

    def __str__(self) -> str:
        """Return string representation of the loan.

        Returns:
            str: Formatted string with loan ID and amount.
        """
        return str(_(f'Кредит №{self.pk} на сумму {self.loan_amount}'))

    def get_absolute_url(self) -> str:
        """Get absolute URL for loan deletion.

        Returns:
            str: URL for deleting this loan.
        """
        return reverse('loan:delete', args=[self.pk])

    @property
    def calculate_sum_monthly_payment(self) -> Decimal:
        """Calculate total sum of monthly payments minus loan amount.

        Returns:
            Decimal: Total interest paid over the loan period.
        """
        payments = self.payment_schedule_loans.aggregate(
            total=models.Sum('monthly_payment'),
        )['total'] or Decimal('0.00')
        return payments - Decimal(str(self.loan_amount))

    @property
    def calculate_total_amount_loan_with_interest(self) -> Decimal:
        """Calculate total amount of loan including interest.

        Returns:
            Decimal: Total amount to be paid including principal and interest.
        """
        sum_monthly_payment = self.calculate_sum_monthly_payment
        return decimal.Decimal(self.loan_amount) + sum_monthly_payment


class PaymentMakeLoan(models.Model):
    """Model representing a loan payment made by the user.

    Stores information about individual payments made towards a loan,
    including date, amount, and associated account.

    Attributes:
        user: Foreign key to the User who made this payment.
        account: Foreign key to the Account used for payment.
        date: Date when the payment was made.
        loan: Foreign key to the Loan this payment is for.
        amount: Amount of the payment.
    """

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
    """Model representing a payment schedule entry for a loan.

    Stores detailed information about each scheduled payment,
    including balance, monthly payment, interest, and principal.

    Attributes:
        user: Foreign key to the User who owns this schedule entry.
        loan: Foreign key to the Loan this schedule is for.
        date: Date of the scheduled payment.
        balance: Remaining loan balance after this payment.
        monthly_payment: Total monthly payment amount.
        interest: Interest portion of the payment.
        principal_payment: Principal portion of the payment.
    """

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
