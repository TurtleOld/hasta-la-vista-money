from typing import TYPE_CHECKING

from django.db.models import Case, DecimalField, F, Value, When
from django.db.models.expressions import Expression

from hasta_la_vista_money import constants

if TYPE_CHECKING:
    from django.db.models.fields import Field


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
