"""Protocol interfaces for user services."""

from hasta_la_vista_money.users.protocols.services import (
    DashboardSummaryStatisticsServiceProtocol,
    UserDetailedStatisticsServiceProtocol,
    UserStatisticsServiceProtocol,
)

__all__ = [
    'DashboardSummaryStatisticsServiceProtocol',
    'UserDetailedStatisticsServiceProtocol',
    'UserStatisticsServiceProtocol',
]
