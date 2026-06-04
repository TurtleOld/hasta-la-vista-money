"""Protocol interfaces for user statistics services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from config.containers import ApplicationContainer
    from hasta_la_vista_money.users.models import User
    from hasta_la_vista_money.users.services.monthly_statistics_service import (
        DashboardSummaryStatisticsDict,
        StatisticsFilters,
    )
    from hasta_la_vista_money.users.services.statistics import UserStatistics
    from hasta_la_vista_money.users.services.summary_statistics_service import (
        UserDetailedStatisticsDict,
    )


@runtime_checkable
class UserStatisticsServiceProtocol(Protocol):
    """Protocol for cached profile statistics service."""

    def get_user_statistics(self, user: User) -> UserStatistics: ...

    def invalidate_cache(self, user: User) -> None: ...


@runtime_checkable
class DashboardSummaryStatisticsServiceProtocol(Protocol):
    """Callable protocol for dashboard summary statistics."""

    def __call__(
        self,
        user: User,
        container: ApplicationContainer,
    ) -> DashboardSummaryStatisticsDict: ...


@runtime_checkable
class UserDetailedStatisticsServiceProtocol(Protocol):
    """Callable protocol for detailed user statistics."""

    def __call__(
        self,
        user: User,
        container: ApplicationContainer,
        stats_filter: StatisticsFilters | None = None,
        page_number: int = 1,
        income_expense_page_number: int = 1,
        transfer_page_number: int = 1,
    ) -> UserDetailedStatisticsDict: ...
