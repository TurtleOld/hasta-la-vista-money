from typing import Optional
from django.http import HttpRequest
from hasta_la_vista_money.finance_account import services as account_services
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import User
from django.db.models import QuerySet

class GroupAccountMixin:
    """
    Mixin to provide group_id and accounts queryset for a user or group.
    """
    request: HttpRequest

    def get_group_id(self) -> Optional[str]:
        return self.request.GET.get('group_id')

    def get_accounts(self, user: User) -> QuerySet[Account]:
        group_id = self.get_group_id()
        return account_services.get_accounts_for_user_or_group(user, group_id) 