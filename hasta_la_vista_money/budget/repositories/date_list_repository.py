"""Django repository for DateList model.

This module provides data access layer for DateList model,
including filtering by user and date.
"""

from datetime import date

from django.db.models import QuerySet

from hasta_la_vista_money.budget.models import DateList
from hasta_la_vista_money.users.models import User


class DateListRepository:
    """Repository for DateList model operations.

    Provides methods for accessing and manipulating date list data.
    """

    def get_by_id(self, date_list_id: int) -> DateList:
        """Get date list by ID.

        Args:
            date_list_id: ID of the date list to retrieve.

        Returns:
            DateList: DateList instance.

        Raises:
            DateList.DoesNotExist: If date list with given ID doesn't exist.
        """
        return DateList.objects.get(pk=date_list_id)

    def get_by_user(self, user: User) -> QuerySet[DateList]:
        """Get all date lists for a user.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[DateList]: QuerySet of user's date lists.
        """
        return DateList.objects.for_user(user)

    def get_by_user_ordered(self, user: User) -> QuerySet[DateList]:
        """Get all date lists for a user ordered by date.

        Args:
            user: User instance to filter by.

        Returns:
            QuerySet[DateList]: QuerySet ordered by date ascending.
        """
        return DateList.objects.for_user(user).order_by('date')

    def get_by_date(self, target_date: date) -> QuerySet[DateList]:
        """Get date lists by date.

        Args:
            target_date: Date to filter by.

        Returns:
            QuerySet[DateList]: Filtered QuerySet.
        """
        return DateList.objects.for_date(target_date)

    def get_by_user_and_date(
        self,
        user: User,
        target_date: date,
    ) -> QuerySet[DateList]:
        """Get date lists for a user by date.

        Args:
            user: User instance to filter by.
            target_date: Date to filter by.

        Returns:
            QuerySet[DateList]: Filtered QuerySet.
        """
        return DateList.objects.for_user(user).for_date(target_date)

    def get_latest_by_user(self, user: User) -> DateList | None:
        """Get latest date list for a user.

        Args:
            user: User instance to filter by.

        Returns:
            DateList | None: Latest date list if exists, None otherwise.
        """
        return DateList.objects.for_user(user).order_by('-date').first()

    def create_date_list(self, **kwargs: object) -> DateList:
        """Create a new date list.

        Args:
            **kwargs: DateList field values (user, date).

        Returns:
            DateList: Created date list instance.
        """
        return DateList.objects.create(**kwargs)

    def bulk_create_date_lists(
        self,
        date_lists: list[DateList],
    ) -> list[DateList]:
        """Create multiple date lists in a single database query.

        Args:
            date_lists: List of DateList instances to create.

        Returns:
            list[DateList]: List of created date list instances.
        """
        return DateList.objects.bulk_create(date_lists)

    def filter(self, **kwargs: object) -> QuerySet[DateList]:
        """Filter date lists by given criteria.

        Args:
            **kwargs: Filter criteria (field=value pairs).

        Returns:
            QuerySet[DateList]: Filtered QuerySet.
        """
        return DateList.objects.filter(**kwargs)
