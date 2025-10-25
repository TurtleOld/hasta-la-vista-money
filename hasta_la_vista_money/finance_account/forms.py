"""Forms for finance account management.

This module contains forms for creating accounts and transferring money
between them.
Forms use base classes and mixins to reduce code duplication and ensure
consistency.
Includes comprehensive validation, user-specific account filtering, and proper
error handling for financial operations.
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.forms import (
    CharField,
    ChoiceField,
    DateField,
    DecimalField,
    IntegerField,
    ModelChoiceField,
)
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.base_forms import (
    BaseAccountForm,
    BaseTransferForm,
    DateFieldMixin,
    FormValidationMixin,
)
from hasta_la_vista_money.finance_account.models import (
    Account,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.services import TransferService
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_credit_fields_required,
    validate_different_accounts,
)
from hasta_la_vista_money.users.models import User


class AddAccountForm(BaseAccountForm, DateFieldMixin):
    """Form for creating a new financial account.

    Supports different account types (debit, credit, cash) with appropriate
    field validation and styling for credit-specific fields. Includes
    comprehensive validation for credit account requirements and proper
    date field configuration.
    """

    name_account = CharField(
        label=_('Наименование счёта'),
        help_text=_(
            'Введите наименование счёта. Максимальная длина 250 символов.',
        ),
        max_length=constants.TWO_HUNDRED_FIFTY,
    )

    type_account = ChoiceField(
        choices=Account.TYPE_ACCOUNT_LIST,
        label=_('Тип счёта'),
        help_text=_('Выберите из списка тип счёта'),
    )

    bank = ChoiceField(
        choices=Account.BANK_LIST,
        label=_('Банк'),
        help_text=_('Выберите банк, выпустивший карту или обслуживающий счёт'),
        required=False,
    )

    limit_credit = DecimalField(
        label=_('Кредитный лимит'),
        help_text=_('Введите кредитный лимит'),
        required=False,
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
    )

    payment_due_date = DateField(
        label=_('Дата платежа'),
        help_text=_('Введите дату платежа'),
        required=False,
    )

    grace_period_days = IntegerField(
        label=_('Длительность льготного периода (дней)'),
        required=False,
        min_value=0,
        max_value=365,
    )

    balance = DecimalField(
        label=_('Баланс'),
        help_text=_(
            'Введите начальный баланс, который есть сейчас на счёту в банке'
            '\\в наличной валюте.\nМаксимальная длина 20 символов.',
        ),
        max_digits=constants.TWENTY,
        decimal_places=constants.TWO,
    )

    currency = ChoiceField(
        choices=Account.CURRENCY_LIST,
        label=_('Валюта счёта'),
        help_text=_('Выберите из списка валюту счёта'),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the form with default values and date field
        configuration."""
        super().__init__(*args, **kwargs)
        # Set default account type
        self.fields['type_account'].initial = Account.TYPE_ACCOUNT_LIST[1][0]
        # Setup date fields
        self.setup_date_fields()

    def clean(self) -> dict[str, Any]:
        """Validate form data, ensuring credit fields are provided for
        credit accounts.

        Performs comprehensive validation including credit field requirements
        and business logic validation for different account types.

        Returns:
            Dict containing cleaned form data.

        Raises:
            ValidationError: If credit fields are missing for credit accounts.
        """
        cleaned_data = super().clean()

        if cleaned_data:
            validate_credit_fields_required(
                type_account=cleaned_data.get('type_account'),
                bank=cleaned_data.get('bank'),
                limit_credit=cleaned_data.get('limit_credit'),
                payment_due_date=cleaned_data.get('payment_due_date'),
                grace_period_days=cleaned_data.get('grace_period_days'),
            )

        return cleaned_data

    class Meta:
        model = Account
        fields = [
            'name_account',
            'type_account',
            'bank',
            'limit_credit',
            'payment_due_date',
            'grace_period_days',
            'balance',
            'currency',
        ]


class TransferMoneyAccountForm(BaseTransferForm, FormValidationMixin):
    """Form for transferring money between accounts.

    Validates transfer parameters and uses TransferService for business logic.
    Supports user-specific account filtering and comprehensive validation
    including balance checks, account differences, and amount validation.
    """

    def __init__(self, user: User, *args: Any, **kwargs: Any) -> None:
        """Initialize transfer form with user-specific account choices.

        Sets up form fields with accounts filtered by the specified user
        and applies Bootstrap styling to all form widgets.

        Args:
            user: User whose accounts should be available for transfer.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(*args, **kwargs)

        user_accounts = Account.objects.filter(user=user)

        self.fields['from_account'] = ModelChoiceField(
            label=_('Со счёта:'),
            queryset=user_accounts,
            help_text=_('Выберите счёт, с которого будет списана сумма'),
        )

        self.fields['to_account'] = ModelChoiceField(
            label=_('На счёт:'),
            queryset=user_accounts,
            help_text=_('Выберите счёт, на который будет зачислена сумма'),
        )

        self.add_bootstrap_classes()

    def clean(self) -> dict[str, Any]:
        """Validate transfer parameters using custom validators.

        Performs comprehensive validation including account differences,
        sufficient balance checks, and amount validation.

        Returns:
            Dict containing cleaned form data.

        Raises:
            ValidationError: If transfer validation fails.
        """
        cleaned_data = super().clean()

        if cleaned_data:
            from_account = cleaned_data.get('from_account')
            to_account = cleaned_data.get('to_account')
            amount = cleaned_data.get('amount')

            if from_account and to_account:
                try:
                    validate_different_accounts(from_account, to_account)
                except ValidationError as e:
                    self.add_error('to_account', e.message)

            if from_account and amount:
                try:
                    validate_account_balance(from_account, amount)
                except ValidationError as e:
                    self.add_error('from_account', e.message)

        return cleaned_data

    def save(self, commit: bool = True) -> TransferMoneyLog:
        """Save the transfer using TransferService.

        Executes the money transfer through the TransferService and creates
        a transfer log entry for audit purposes.

        Args:
            commit: Whether to commit the transfer to database.

        Returns:
            TransferMoneyLog: Created transfer log entry.

        Raises:
            ValueError: If transfer fails due to insufficient funds or
            invalid accounts.
        """
        if not commit:
            error_msg = 'Transfer forms must be committed'
            raise ValueError(error_msg)

        cleaned_data = self.cleaned_data

        return TransferService.transfer_money(
            from_account=cleaned_data['from_account'],
            to_account=cleaned_data['to_account'],
            amount=cleaned_data['amount'],
            user=cleaned_data['from_account'].user,
            exchange_date=cleaned_data.get('exchange_date'),
            notes=cleaned_data.get('notes'),
        )

    class Meta:
        model = TransferMoneyLog
        fields = [
            'from_account',
            'to_account',
            'exchange_date',
            'amount',
            'notes',
        ]
        labels = {
            'exchange_date': _('Дата перевода'),
        }
