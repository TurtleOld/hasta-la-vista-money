"""Django repository for PaymentMakeLoan model.

This module provides data access layer for PaymentMakeLoan model,
including filtering and CRUD operations.
"""

from django.db.models import QuerySet

from hasta_la_vista_money.loan.models import Loan, PaymentMakeLoan
from hasta_la_vista_money.users.models import User


class PaymentMakeLoanRepository:
    """Repository for PaymentMakeLoan model operations.

    Provides methods for accessing and manipulating loan payment data.
    """

    def get_by_id(self, payment_id: int) -> PaymentMakeLoan:
        """Get payment by ID.

        Args:
            payment_id: ID of the payment to retrieve.

        Returns:
            PaymentMakeLoan: Payment instance.

        Raises:
            PaymentMakeLoan.DoesNotExist: If payment with given ID
                doesn't exist.
        """
        return PaymentMakeLoan.objects.get(pk=payment_id)

    def get_by_user(self, user: User) -> QuerySet[PaymentMakeLoan]:
        """Get all payments for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[PaymentMakeLoan]: QuerySet of user's payments.
        """
        return PaymentMakeLoan.objects.filter(user=user)

    def get_by_loan(self, loan: Loan) -> QuerySet[PaymentMakeLoan]:
        """Get all payments for a loan.

        Args:
            loan: Loan instance to filter by.

        Returns:
            QuerySet[PaymentMakeLoan]: Filtered QuerySet.
        """
        return PaymentMakeLoan.objects.filter(loan=loan)

    def get_by_user_with_related(self, user: User) -> QuerySet[PaymentMakeLoan]:
        """Get all payments for a user with related objects optimized.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[PaymentMakeLoan]: QuerySet with select_related
                optimizations.
        """
        return PaymentMakeLoan.objects.filter(user=user).select_related(
            'user', 'account', 'loan'
        )

    def create_payment(self, **kwargs: object) -> PaymentMakeLoan:
        """Create a new payment.

        Args:
            **kwargs: Payment field values (user, account, loan, date, amount).

        Returns:
            PaymentMakeLoan: Created payment instance.
        """
        return PaymentMakeLoan.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[PaymentMakeLoan]:
        """Filter payments by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[PaymentMakeLoan]: Filtered QuerySet.
        """
        return PaymentMakeLoan.objects.filter(**kwargs)
