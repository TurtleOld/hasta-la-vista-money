from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import Case, DecimalField, F, Q, Sum, Value, When
from django.db.models.expressions import Expression

from hasta_la_vista_money import constants
from hasta_la_vista_money.deposits.models import DepositCapitalizationEvent

if TYPE_CHECKING:
    from django.db.models.fields import Field

    from hasta_la_vista_money.users.models import User


def signed_interest(field: str) -> Expression:
    output_field: Field[object, object] = DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
    )
    return Case(
        When(
            reversal_of__isnull=False,
            then=Value(-1, output_field=output_field) * F(field),
        ),
        default=F(field),
        output_field=output_field,
    )


def signed_adjustment_income() -> Expression:
    output_field: Field[object, object] = DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
    )
    return Case(
        When(
            reversal_of__isnull=True,
            prior_interest_adjustment__gt=0,
            then=F('prior_interest_adjustment'),
        ),
        When(
            reversal_of__isnull=False,
            prior_interest_adjustment__lt=0,
            then=-F('prior_interest_adjustment'),
        ),
        default=Value(0),
        output_field=output_field,
    )


def signed_adjustment_expense() -> Expression:
    output_field: Field[object, object] = DecimalField(
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
    )
    return Case(
        When(
            reversal_of__isnull=True,
            prior_interest_adjustment__lt=0,
            then=-F('prior_interest_adjustment'),
        ),
        When(
            reversal_of__isnull=False,
            prior_interest_adjustment__gt=0,
            then=F('prior_interest_adjustment'),
        ),
        default=Value(0),
        output_field=output_field,
    )


def actual_interest_totals_for_periods(
    users: Iterable['User'],
    periods: dict[str, tuple[date, date]],
    currency: str,
) -> dict[str, tuple[Decimal, Decimal]]:
    """Return actual deposit totals in `currency` for named periods."""
    aggregates: dict[str, Any] = {}
    for name, (start, end) in periods.items():
        period_filter = Q(posting_on__gte=start, posting_on__lte=end)
        aggregates.update(
            {
                f'{name}_gross': Sum(
                    signed_interest('gross'),
                    filter=period_filter,
                ),
                f'{name}_withholding': Sum(
                    signed_interest('withholding'),
                    filter=period_filter,
                ),
                f'{name}_adjustment_income': Sum(
                    signed_adjustment_income(),
                    filter=period_filter,
                ),
                f'{name}_adjustment_expense': Sum(
                    signed_adjustment_expense(),
                    filter=period_filter,
                ),
            },
        )
    totals = DepositCapitalizationEvent.objects.filter(
        deposit__account__user__in=users,
        deposit__account__currency=currency,
    ).aggregate(**aggregates)
    return {
        name: (
            Decimal(totals[f'{name}_gross'] or constants.ZERO)
            + Decimal(
                totals[f'{name}_adjustment_income'] or constants.ZERO,
            ),
            Decimal(totals[f'{name}_withholding'] or constants.ZERO)
            + Decimal(
                totals[f'{name}_adjustment_expense'] or constants.ZERO,
            ),
        )
        for name in periods
    }
