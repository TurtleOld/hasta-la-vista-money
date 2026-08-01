from django.db.models import QuerySet

from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositRatePeriod,
    DepositTerm,
)
from hasta_la_vista_money.users.models import User


class DepositRepository:
    def create_deposit(self, **kwargs: object) -> Deposit:
        return Deposit.objects.create(**kwargs)

    def create_term(self, **kwargs: object) -> DepositTerm:
        return DepositTerm.objects.create(**kwargs)

    def create_rate_period(self, **kwargs: object) -> DepositRatePeriod:
        return DepositRatePeriod.objects.create(**kwargs)

    def get_by_user(self, user: User) -> QuerySet[Deposit]:
        return (
            Deposit.objects.filter(account__user=user)
            .select_related('account')
            .prefetch_related('terms__rate_periods')
        )

    def get_by_id_and_user(self, deposit_id: int, user: User) -> Deposit:
        return self.get_by_user(user).get(pk=deposit_id)
