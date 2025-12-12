"""Django repository for Loan model.

This module provides data access layer for Loan model,
including filtering and CRUD operations.
"""

from django.db.models import QuerySet

from hasta_la_vista_money.loan.models import Loan
from hasta_la_vista_money.users.models import User


class LoanRepository:
    """Repository for Loan model operations.

    Provides methods for accessing and manipulating loan data.
    """

    def get_by_id(self, loan_id: int) -> Loan:
        """Get loan by ID.

        Args:
            loan_id: ID of the loan to retrieve.

        Returns:
            Loan: Loan instance.

        Raises:
            Loan.DoesNotExist: If loan with given ID doesn't exist.
        """
        return Loan.objects.get(pk=loan_id)

    def get_by_user(self, user: User) -> QuerySet[Loan]:
        """Get all loans for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Loan]: QuerySet of user's loans.
        """
        return Loan.objects.filter(user=user)

    def get_by_user_with_related(self, user: User) -> QuerySet[Loan]:
        """Get all loans for a user with related objects optimized.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[Loan]: QuerySet with select_related optimizations applied.
        """
        return Loan.objects.filter(user=user).select_related('user', 'account')

    def create_loan(self, **kwargs: object) -> Loan:
        """Create a new loan.

        Args:
            **kwargs: Loan field values (user, account, date, loan_amount,
                annual_interest_rate, period_loan, type_loan).

        Returns:
            Loan: Created loan instance.
        """
        return Loan.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[Loan]:
        """Filter loans by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[Loan]: Filtered QuerySet.
        """
        return Loan.objects.filter(**kwargs)
