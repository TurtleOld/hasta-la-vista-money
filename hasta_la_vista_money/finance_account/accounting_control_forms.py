"""Filter form for the unified accounting control page."""

from django.forms import CharField, DateField, Form, IntegerField
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.users.accounting_types import (
    ProblemKind,
    ProblemState,
)

_ACCOUNT_ERROR = _('Некорректное значение счёта в фильтре.')


class AccountingControlFilterForm(Form):
    """Validate optional accounting-control filters without hand parsing."""

    account = IntegerField(
        required=False,
        min_value=1,
        max_value=constants.DATABASE_BIGINT_MAX,
        error_messages={
            'invalid': _ACCOUNT_ERROR,
            'min_value': _ACCOUNT_ERROR,
            'max_value': _ACCOUNT_ERROR,
        },
    )
    bank = CharField(required=False, strip=False)
    currency = CharField(required=False, strip=False)
    kind = CharField(required=False, strip=False)
    state = CharField(required=False, strip=False)
    date_from = DateField(
        required=False,
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        error_messages={
            'invalid': _('Некорректная дата начала в фильтре.'),
        },
    )
    date_to = DateField(
        required=False,
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        error_messages={
            'invalid': _('Некорректная дата конца в фильтре.'),
        },
    )

    def clean_kind(self) -> str:
        """Keep an unknown kind equivalent to no kind filter."""
        value = self.cleaned_data.get('kind') or ''
        return value if value in set(ProblemKind) else ''

    def clean_state(self) -> str:
        """Keep an unknown state equivalent to the all state."""
        value = self.cleaned_data.get('state') or ''
        return value if value in set(ProblemState) else ProblemState.ALL
