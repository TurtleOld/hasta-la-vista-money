from typing import TYPE_CHECKING

from django.db.models import QuerySet

from hasta_la_vista_money.deposits.models import (
    Deposit,
    DepositCapitalizationEvent,
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
            .prefetch_related(
                'terms__rate_periods',
                'terms__payout_schedule_dates',
                'terms__interest_forecasts',
            )
        )

    def get_by_id_and_user(self, deposit_id: int, user: User) -> Deposit:
        return self.get_by_user(user).get(pk=deposit_id)

    def get_by_id_and_user_for_update(
        self,
        deposit_id: int,
        user: User,
    ) -> Deposit:
        return (
            Deposit.objects.select_for_update()
            .select_related('account')
            .prefetch_related('terms')
            .get(pk=deposit_id, account__user=user)
        )

    def get_term_by_id_and_user(
        self,
        term_id: int,
        user: User,
    ) -> DepositTerm:
        return DepositTerm.objects.select_related('deposit__account').get(
            pk=term_id,
            deposit__account__user=user,
        )

    def get_overlapping_terms(
        self,
        deposit_id: int,
        opened_on: 'date',
        matures_on: 'date',
    ) -> QuerySet[DepositTerm]:
        return DepositTerm.objects.filter(
            deposit_id=deposit_id,
            opened_on__lte=matures_on,
            matures_on__gte=opened_on,
        )

    def mark_term_not_current(self, term_id: int) -> DepositTerm:
        term = DepositTerm.objects.get(pk=term_id)
        term.is_current = False
        term.save(update_fields=['is_current'])
        return term

    def trim_rate_period_end(
        self,
        period_id: int,
        new_ends_on: 'date',
    ) -> None:
        DepositRatePeriod.objects.filter(pk=period_id).update(
            ends_on=new_ends_on,
        )

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

    def create_capitalization_event(
        self,
        **kwargs: object,
    ) -> DepositCapitalizationEvent:
        return DepositCapitalizationEvent.objects.create(**kwargs)

    def get_planned_closure_event(
        self,
        deposit_id: int,
    ) -> DepositPrincipalEvent | None:
        return DepositPrincipalEvent.objects.filter(
            deposit_id=deposit_id,
            type=DepositPrincipalEvent.Type.PLANNED_CLOSURE,
        ).first()

    def get_final_interest_event(
        self,
        deposit_id: int,
    ) -> DepositCapitalizationEvent | None:
        return DepositCapitalizationEvent.objects.filter(
            deposit_id=deposit_id,
            is_final=True,
        ).first()

    def close_term(self, term_id: int, closed_on: 'date') -> None:
        DepositTerm.objects.filter(pk=term_id).update(closed_on=closed_on)

    def get_forecast_for_update(
        self,
        forecast_id: int,
        term_id: int,
    ) -> DepositInterestForecast:
        return DepositInterestForecast.objects.select_for_update().get(
            pk=forecast_id,
            term_id=term_id,
        )

    def confirm_forecast(self, forecast_id: int) -> None:
        DepositInterestForecast.objects.filter(pk=forecast_id).update(
            confirmed=True,
        )

    def delete_unconfirmed_forecasts(self, term_id: int) -> None:
        DepositInterestForecast.objects.filter(
            term_id=term_id,
            confirmed=False,
        ).delete()
