"""Django repository for PaymentSchedule model.

This module provides data access layer for PaymentSchedule model,
including filtering and CRUD operations.
"""

from django.db.models import QuerySet

from hasta_la_vista_money.loan.models import Loan, PaymentSchedule
from hasta_la_vista_money.users.models import User


class PaymentScheduleRepository:
    """Repository for PaymentSchedule model operations.

    Provides methods for accessing and manipulating payment schedule data.
    """

    def get_by_id(self, schedule_id: int) -> PaymentSchedule:
        """Get schedule by ID.

        Args:
            schedule_id: ID of the schedule to retrieve.

        Returns:
            PaymentSchedule: Schedule instance.

        Raises:
            PaymentSchedule.DoesNotExist: If schedule with given ID
                doesn't exist.
        """
        return PaymentSchedule.objects.get(pk=schedule_id)

    def get_by_user(self, user: User) -> QuerySet[PaymentSchedule]:
        """Get all schedules for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[PaymentSchedule]: QuerySet of user's schedules.
        """
        return PaymentSchedule.objects.filter(user=user)

    def get_by_loan(self, loan: Loan) -> QuerySet[PaymentSchedule]:
        """Get all schedules for a loan.

        Args:
            loan: Loan instance to filter by.

        Returns:
            QuerySet[PaymentSchedule]: Filtered QuerySet.
        """
        return PaymentSchedule.objects.filter(loan=loan)

    def get_by_loans(
        self,
        loan_ids: list[int],
    ) -> QuerySet[PaymentSchedule]:
        """Get all schedules for a list of loan IDs.

        Args:
            loan_ids: List of loan IDs to filter by.

        Returns:
            QuerySet[PaymentSchedule]: Filtered QuerySet.
        """
        return PaymentSchedule.objects.filter(loan_id__in=loan_ids)

    def get_by_user_with_related(self, user: User) -> QuerySet[PaymentSchedule]:
        """Get all schedules for a user with related objects optimized.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[PaymentSchedule]: QuerySet with select_related
                optimizations.
        """
        return PaymentSchedule.objects.filter(user=user).select_related(
            'user', 'loan'
        )

    def bulk_create_schedules(
        self,
        schedules: list[PaymentSchedule],
    ) -> list[PaymentSchedule]:
        """Create multiple schedules in a single database query.

        Args:
            schedules: List of PaymentSchedule instances to create.

        Returns:
            list[PaymentSchedule]: List of created schedule instances.
        """
        return PaymentSchedule.objects.bulk_create(schedules)

    def create_schedule(self, **kwargs: object) -> PaymentSchedule:
        """Create a new schedule.

        Args:
            **kwargs: Schedule field values (user, loan, date, balance,
                monthly_payment, interest, principal_payment).

        Returns:
            PaymentSchedule: Created schedule instance.
        """
        return PaymentSchedule.objects.create(**kwargs)

    def filter(self, **kwargs: object) -> QuerySet[PaymentSchedule]:
        """Filter schedules by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[PaymentSchedule]: Filtered QuerySet.
        """
        return PaymentSchedule.objects.filter(**kwargs)

    def delete_by_loan(self, loan: Loan) -> tuple[int, dict[str, int]]:
        """Delete all schedules for a loan.

        Args:
            loan: Loan instance to filter by.

        Returns:
            tuple[int, dict[str, int]]: Tuple of (number deleted, dict with
                deletion details).
        """
        return PaymentSchedule.objects.filter(loan=loan).delete()
