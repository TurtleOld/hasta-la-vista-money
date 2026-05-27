from django.core.cache import cache

from hasta_la_vista_money.core.types import RequestWithContainer as AuthRequest
from hasta_la_vista_money.users.services.dashboard_analytics import (
    get_drill_down_data,
    get_period_comparison,
)
from hasta_la_vista_money.users.services.detailed_statistics import (
    get_dashboard_summary_statistics,
)
from hasta_la_vista_money.users.tasks import process_bank_statement_task
from hasta_la_vista_money.users.views.auth import (
    CreateUser,
    LoginUser,
    LogoutUser,
    SetPasswordUserView,
)
from hasta_la_vista_money.users.views.bank_statement import (
    BankStatementUploadStatusView,
    BankStatementUploadView,
)
from hasta_la_vista_money.users.views.base import IndexView
from hasta_la_vista_money.users.views.dashboard import (
    DashboardComparisonView,
    DashboardDataView,
    DashboardDrillDownView,
    DashboardView,
    DashboardWidgetConfigView,
)
from hasta_la_vista_money.users.views.groups import (
    AddUserToGroupView,
    DeleteUserFromGroupView,
    GroupCreateView,
    GroupDeleteView,
    JoinFamilyGroupView,
)
from hasta_la_vista_money.users.views.profile import (
    ExportUserDataView,
    ListUsers,
    SwitchThemeView,
    UpdateUserView,
    UserNotificationsView,
    UserStatisticsExportView,
    UserStatisticsView,
)

__all__ = [
    'AddUserToGroupView',
    'AuthRequest',
    'BankStatementUploadStatusView',
    'BankStatementUploadView',
    'CreateUser',
    'DashboardComparisonView',
    'DashboardDataView',
    'DashboardDrillDownView',
    'DashboardView',
    'DashboardWidgetConfigView',
    'DeleteUserFromGroupView',
    'ExportUserDataView',
    'GroupCreateView',
    'GroupDeleteView',
    'IndexView',
    'JoinFamilyGroupView',
    'ListUsers',
    'LoginUser',
    'LogoutUser',
    'SetPasswordUserView',
    'SwitchThemeView',
    'UpdateUserView',
    'UserNotificationsView',
    'UserStatisticsExportView',
    'UserStatisticsView',
    'cache',
    'get_dashboard_summary_statistics',
    'get_drill_down_data',
    'get_period_comparison',
    'process_bank_statement_task',
]
