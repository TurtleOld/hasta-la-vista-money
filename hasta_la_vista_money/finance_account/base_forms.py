"""Base form classes and mixins for finance account forms.

This module provides reusable base classes and mixins to reduce code duplication
and ensure consistent behavior across forms. It includes
Bootstrap styling mixins,
credit field handling, date field configuration, and common validation patterns.
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.forms import (
    CharField,
    DateInput,
    DateTimeInput,
    DecimalField,
    ModelForm,
    Textarea,
)
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)


class BootstrapFormMixin:
    """Mixin to add Bootstrap CSS classes to form widgets.

    Automatically applies Bootstrap form-control classes to all form fields
    to ensure consistent styling across the application.
    """

    def add_bootstrap_classes(self) -> None:
        """Add Bootstrap CSS classes to all form widgets.

        Iterates through all form fields and adds the 'form-control' class
        to their widget attributes if not already present.
        """
        for field in self.fields.values():  # type: ignore[attr-defined]
            if hasattr(field.widget, 'attrs'):
                current_class = field.widget.attrs.get('class', '')
                if 'form-control' not in current_class:
                    field.widget.attrs['class'] = (
                        f'{current_class} form-control'.strip()
                    )


class CreditFieldsMixin:
    """Mixin to handle credit-specific field styling.

    Applies special CSS classes to credit-related fields to enable
    conditional styling and behavior in the frontend.
    """

    def add_credit_field_classes(self) -> None:
        """Add CSS classes for credit-only fields.

        Applies the 'credit-only-field' class to credit-related form fields
        including limit_credit, payment_due_date, and grace_period_days.
        """
        credit_fields = [
            'limit_credit',
            'payment_due_date',
            'grace_period_days',
        ]

        for field_name in credit_fields:
            if field_name in self.fields:  # type: ignore[attr-defined]
                current_class = self.fields[field_name].widget.attrs.get(  # type: ignore[attr-defined]
                    'class',
                    '',
                )
                self.fields[field_name].widget.attrs['class'] = (  # type: ignore[attr-defined]
                    f'{current_class} credit-only-field'.strip()
                )


class DateFieldMixin:
    """Mixin for forms with date fields.

    Provides configuration for date and datetime fields with appropriate
    HTML5 input types and Bootstrap styling.
    """

    def setup_date_fields(self) -> None:
        """Configure date fields with appropriate widgets.

        Sets up payment_due_date with a date input widget and exchange_date
        with a datetime-local input widget, both with Bootstrap styling.
        """
        if 'payment_due_date' in self.fields:  # type: ignore[attr-defined]
            self.fields['payment_due_date'].widget = DateInput(  # type: ignore[attr-defined]
                attrs={
                    'type': 'date',
                    'class': 'form-control credit-only-field',
                },
            )

        if 'exchange_date' in self.fields:  # type: ignore[attr-defined]
            self.fields['exchange_date'].widget = DateTimeInput(  # type: ignore[attr-defined]
                attrs={
                    'type': 'datetime-local',
                    'class': 'form-control',
                },
            )


class FormValidationMixin:
    """Mixin for common form validation patterns.

    Provides reusable validation methods for forms, including amount validation
    and error message creation utilities.
    """

    def clean_amount(self) -> Any:
        """Validate amount field.

        Ensures the amount is positive and greater than zero.

        Returns:
            The validated amount value.

        Raises:
            ValidationError: If amount is zero or negative.
        """
        amount = self.cleaned_data.get('amount')  # type: ignore[attr-defined]
        if amount is not None and amount <= 0:
            msg = 'amount'
            raise self.get_form_error(
                msg,
                str(_('Сумма должна быть больше нуля')),
            )
        return amount

    def get_form_error(self, field: str, message: str) -> Any:
        """Create a form validation error.

        Args:
            field: The field name for the error.
            message: The error message text.

        Returns:
            ValidationError: A Django validation error instance.
        """
        return ValidationError(message, code='invalid_value')


class BaseAccountForm(
    BootstrapFormMixin, CreditFieldsMixin, ModelForm[Account]
):
    """Base form class for account-related forms with common functionality.

    Combines Bootstrap styling, credit field handling, and
    ModelForm functionality
    to provide a consistent foundation for account creation and editing forms.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the form with Bootstrap and credit field styling."""
        super().__init__(*args, **kwargs)
        self.add_bootstrap_classes()
        self.add_credit_field_classes()


class BaseTransferForm(BootstrapFormMixin, ModelForm[TransferMoneyLog]):
    """Base form class for transfer-related forms.

    Provides Bootstrap styling and common field configuration for money
    transfer forms, including amount and notes fields with appropriate widgets.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        if 'amount' not in self.fields:
            self.fields['amount'] = DecimalField(
                label=_('Сумма'),
                max_digits=constants.TWENTY,
                decimal_places=constants.TWO,
                help_text=_('Введите сумму перевода'),
            )

        if 'notes' not in self.fields:
            self.fields['notes'] = CharField(
                label=_('Заметка'),
                required=False,
                help_text=constants.ACCOUNT_FORM_NOTES,
                widget=Textarea(
                    attrs={
                        'rows': 3,
                        'maxlength': constants.TWO_HUNDRED_FIFTY,
                        'class': 'form-control',
                    },
                ),
            )

        self.add_bootstrap_classes()
