"""
Base form classes and mixins for finance account forms.

This module provides reusable base classes and mixins to reduce code duplication
and ensure consistent behavior across forms.
"""

from typing import Any

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
from django.core.exceptions import ValidationError


class BootstrapFormMixin:
    """Mixin to add Bootstrap CSS classes to form widgets."""

    def add_bootstrap_classes(self) -> None:
        """Add Bootstrap CSS classes to all form widgets."""
        for field_name, field in self.fields.items():
            if hasattr(field.widget, 'attrs'):
                current_class = field.widget.attrs.get('class', '')
                if 'form-control' not in current_class:
                    field.widget.attrs['class'] = (
                        f'{current_class} form-control'.strip()
                    )


class CreditFieldsMixin:
    """Mixin to handle credit-specific field styling."""

    def add_credit_field_classes(self) -> None:
        """Add CSS classes for credit-only fields."""
        credit_fields = ['limit_credit', 'payment_due_date', 'grace_period_days']

        for field_name in credit_fields:
            if field_name in self.fields:
                current_class = self.fields[field_name].widget.attrs.get('class', '')
                self.fields[field_name].widget.attrs['class'] = (
                    f'{current_class} credit-only-field'.strip()
                )


class DateFieldMixin:
    """Mixin for forms with date fields."""

    def setup_date_fields(self) -> None:
        """Configure date fields with appropriate widgets."""
        if 'payment_due_date' in self.fields:
            self.fields['payment_due_date'].widget = DateInput(
                attrs={
                    'type': 'date',
                    'class': 'form-control credit-only-field',
                },
            )

        if 'exchange_date' in self.fields:
            self.fields['exchange_date'].widget = DateTimeInput(
                attrs={
                    'type': 'datetime-local',
                    'class': 'form-control',
                },
            )


class FormValidationMixin:
    """Mixin for common form validation patterns."""

    def clean_amount(self) -> Any:
        """Validate amount field."""
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise self.get_form_error('amount', _('Сумма должна быть больше нуля'))
        return amount

    def get_form_error(self, field: str, message: str) -> Any:
        """Helper method to create form errors."""
        return ValidationError(message, code='invalid_value')


class BaseAccountForm(BootstrapFormMixin, CreditFieldsMixin, ModelForm):
    """Base form class for account-related forms with common functionality."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.add_bootstrap_classes()
        self.add_credit_field_classes()


class BaseTransferForm(BootstrapFormMixin, ModelForm):
    """Base form class for transfer-related forms."""

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
