from typing import TYPE_CHECKING

from django.db.models import QuerySet

from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositInterestForecast,
    DepositPayoutScheduleDate,
    DepositPrincipalEvent,
    DepositRatePeriod,
    DepositTerm,
)
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from datetime import date

    from hasta_la_vista_money.deposits.interest_forecast import ForecastLine


class DepositRepository:
    def create_deposit(self, **kwargs: object) -> Deposit:
        return Deposit.objects.create(**kwargs)

    def create_term(self, **kwargs: object) -> DepositTerm:
        return DepositTerm.objects.create(**kwargs)

    def create_rate_period(self, **kwargs: object) -> DepositRatePeriod:
        return DepositRatePeriod.objects.create(**kwargs)

    def create_payout_schedule_date(
        self,
        **kwargs: object,
    ) -> DepositPayoutScheduleDate:
        return DepositPayoutScheduleDate.objects.create(**kwargs)

    def create_principal_event(
        self,
        **kwargs: object,
    ) -> DepositPrincipalEvent:
        """Persist a new immutable deposit principal event.

        Args:
            **kwargs: Fields for the DepositPrincipalEvent instance.

        Returns:
            The persisted DepositPrincipalEvent.
        """
        return DepositPrincipalEvent.objects.create(**kwargs)

    def get_by_user(self, user: User) -> QuerySet[Deposit]:
        return (
            Deposit.objects.filter(account__user=user)
            .select_related('account')
            .prefetch_related('terms__rate_periods')
        )

    def get_by_id_and_user(self, deposit_id: int, user: User) -> Deposit:
        return self.get_by_user(user).get(pk=deposit_id)

    def get_term_by_id_and_user(
        self,
        term_id: int,
        user: User,
    ) -> DepositTerm:
        return DepositTerm.objects.select_related('deposit__account').get(
            pk=term_id,
            deposit__account__user=user,
        )

    def trim_rate_period_end(
        self,
        period_id: int,
        new_ends_on: 'date',
    ) -> None:
        DepositRatePeriod.objects.filter(pk=period_id).update(
            ends_on=new_ends_on,
        )

    def delete_unconfirmed_forecasts(self, term_id: int) -> None:
        DepositInterestForecast.objects.filter(
            term_id=term_id,
            confirmed=False,
        ).delete()

    def delete_future_unconfirmed_forecasts(
        self,
        term_id: int,
        effective_on: 'date',
    ) -> None:
        DepositInterestForecast.objects.filter(
            term_id=term_id,
            confirmed=False,
            payout_on__gte=effective_on,
        ).delete()

    def create_forecast_lines(
        self,
        term: DepositTerm,
        lines: list['ForecastLine'],
    ) -> list[DepositInterestForecast]:
        return DepositInterestForecast.objects.bulk_create(
            [
                DepositInterestForecast(
                    term=term,
                    payout_on=line.payout_on,
                    amount=line.amount,
                    period_starts_on=line.period_starts_on,
                    period_ends_on=line.period_ends_on,
                    is_rate_undefined=line.is_rate_undefined,
                    is_date_tentative=line.is_date_tentative,
                )
                for line in lines
            ],
        )
