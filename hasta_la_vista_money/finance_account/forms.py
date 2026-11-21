"""Forms for finance account management.

This module contains forms for creating accounts and transferring money
between them.
Forms use base classes and mixins to reduce code duplication and ensure
consistency.
Includes comprehensive validation, user-specific account filtering, and proper
error handling for financial operations.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from typing import Any, cast
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db.models import Q, TextChoices
from django.forms import (
    BooleanField,
    CharField,
    ChoiceField,
    DateField,
    DateInput,
    DateTimeField,
    DecimalField,
    FileField,
    FileInput,
    Form,
    HiddenInput,
    IntegerField,
    ModelChoiceField,
    Select,
    Textarea,
)
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _

from hasta_la_vista_money import constants
from hasta_la_vista_money.finance_account.base_forms import (
    BaseAccountForm,
    BaseTransferForm,
    DateFieldMixin,
    FormValidationMixin,
    TailwindFormMixin,
)
from hasta_la_vista_money.finance_account.currencies import currency_choices
from hasta_la_vista_money.finance_account.models import (
    Account,
    AccountCoverageConfirmation,
    AccountManager,
    Bank,
    TransferMoneyLog,
)
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_credit_fields_required,
    validate_different_accounts,
    validate_same_currency,
)
from hasta_la_vista_money.transactions.models import (
    Transaction,
    TransactionType,
)
from hasta_la_vista_money.users.models import BankStatementUpload, User

# The project manager adds typed querysets; ``Manager`` is what Django's
# typing exposes, so narrow it once here instead of at every use.
_OBJECTS_ATTR = 'objects'

_account_manager: AccountManager = getattr(Account, _OBJECTS_ATTR)


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
        choices=[
            choice
            for choice in Account.TYPE_ACCOUNT_LIST
            if choice[0] in constants.MANUALLY_CREATABLE_ACCOUNT_TYPES
        ],
        label=_('Тип счёта'),
        help_text=_('Выберите из списка тип счёта'),
    )

    bank = ModelChoiceField(
        queryset=Bank.objects.none(),
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
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
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
        choices=currency_choices(),
        label=_('Валюта счёта'),
        help_text=_('Выберите из списка валюту счёта'),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the form with default values and date field
        configuration."""
        self.request_user: User | None = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['type_account'].initial = Account.TYPE_ACCOUNT_LIST[1][0]
        self.setup_date_fields()
        self._setup_life_date_fields()
        if self.instance.pk:
            # Balance moves only via movements; currency only while empty.
            del self.fields['balance']
            if self.instance.has_movements():
                del self.fields['currency']
        if self.request_user is not None:
            bank_field = cast(
                'ModelChoiceField[Bank]',
                self.fields['bank'],
            )
            bank_field.queryset = Bank.objects.filter(
                Q(is_system=True) | Q(user=self.request_user),
            )
        else:
            bank_field = cast(
                'ModelChoiceField[Bank]',
                self.fields['bank'],
            )
            bank_field.queryset = Bank.objects.filter(
                is_system=True,
            )

    def _setup_life_date_fields(self) -> None:
        """Use calendar date inputs for the optional account life bounds."""
        for field_name in ('opened_on', 'closed_on'):
            field = self.fields[field_name]
            field.widget = DateInput(
                format=constants.HTML5_DATE_INPUT_FORMAT,
                attrs={
                    'type': 'date',
                    'lang': 'ru-RU',
                    'class': (
                        'w-full rounded-xl border border-gray-300 bg-white '
                        'px-3 py-2 text-sm text-gray-900 shadow-sm'
                    ),
                },
            )
            if isinstance(field, DateField):
                field.input_formats = list(constants.HTML5_DATE_INPUT_FORMATS)

    def clean_balance(self) -> Any:
        """Validate balance field.

        Ensures the balance is not negative for non-credit accounts.

        Returns:
            The validated balance value.

        Raises:
            ValidationError: If balance is negative for non-credit accounts.
        """
        balance = self.cleaned_data.get('balance')
        type_account = self.cleaned_data.get('type_account')

        if (
            balance is not None
            and balance < 0
            and type_account not in constants.CREDIT_ACCOUNT_TYPES
        ):
            raise ValidationError(
                _('Баланс не может быть отрицательным для данного типа счёта'),
                code='invalid_balance',
            )
        return balance

    def clean_bank(self) -> Bank:
        """Use the default bank value for non-credit accounts."""
        bank: Bank | None = self.cleaned_data.get('bank')
        if bank is None:
            return Bank.objects.get(code='-')
        return bank

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
            opened_on = cleaned_data.get('opened_on')
            closed_on = cleaned_data.get('closed_on')
            if (
                opened_on is not None
                and closed_on is not None
                and opened_on > closed_on
            ):
                self.add_error(
                    'opened_on',
                    _('Дата открытия не может быть позже даты закрытия'),
                )
            validate_credit_fields_required(
                type_account=cleaned_data.get('type_account'),
                bank=cleaned_data.get('bank'),
                limit_credit=cleaned_data.get('limit_credit'),
                payment_due_date=cleaned_data.get('payment_due_date'),
                grace_period_days=cleaned_data.get('grace_period_days'),
            )
            self._validate_credit_type_change(cleaned_data)

        return cleaned_data or {}

    def _validate_credit_type_change(
        self,
        cleaned_data: dict[str, Any],
    ) -> None:
        """Reject switching an account with incomes to a credit type."""
        account = self.instance
        type_account = cleaned_data.get('type_account')
        if (
            account.pk
            and type_account in constants.CREDIT_ACCOUNT_TYPES
            and account.type_account not in constants.CREDIT_ACCOUNT_TYPES
            and Transaction.objects.filter(
                account=account,
                type=TransactionType.INCOME,
            ).exists()
        ):
            self.add_error(
                'type_account',
                constants.CREDIT_CARD_HAS_INCOME_BAN,
            )

    class Meta:
        model = Account
        fields = [
            'name_account',
            'type_account',
            'bank',
            'account_number',
            'limit_credit',
            'payment_due_date',
            'grace_period_days',
            'balance',
            'currency',
            'opened_on',
            'closed_on',
        ]

    def save(self, commit: bool = True) -> Account:
        """Create Account instance and set user if provided.

        If no user was provided to the form, the instance will not be saved
        even if commit=True, to avoid IntegrityError on required user field.
        """
        instance: Account = super().save(commit=False)
        if commit and self.request_user is not None:
            instance.user = self.request_user
            instance.save()
        return instance


class TransferMoneyAccountForm(BaseTransferForm, FormValidationMixin):
    """Form for transferring money between accounts.

    Validates transfer parameters and uses TransferService for business logic.
    Supports user-specific account filtering and comprehensive validation
    including balance checks, account differences, and amount validation.
    """

    statement_row = IntegerField(
        required=False,
        widget=HiddenInput,
        error_messages={'invalid': _('Строка выписки не найдена.')},
    )

    def __init__(
        self,
        user: User,
        transfer_service: Any,
        account_repository: Any,
        *args: Any,
        bank_day: date | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize transfer form with user-specific account choices.

        Sets up form fields with accounts filtered by the specified user
        and applies Tailwind styling to all form widgets. A statement-linked
        transfer with a known bank day renders a date-only field instead of
        exposing the technical timestamp as bank time.

        Args:
            user: User whose accounts should be available for transfer.
            transfer_service: TransferService instance from DI container.
            account_repository: AccountRepository instance from DI container.
            *args: Additional positional arguments.
            bank_day: Known bank day of the owned statement row, if any.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(*args, **kwargs)
        self.transfer_service = transfer_service
        self.account_repository = account_repository
        self.bank_day = bank_day
        if bank_day is not None:
            self.fields['exchange_date'] = DateTimeField(
                label=_('Дата перевода'),
                widget=DateInput(
                    format=constants.HTML5_DATE_WIRE_FORMAT,
                    attrs={
                        'type': 'date',
                        'data-flatpickr': 'true',
                        'data-flatpickr-mode': 'date',
                    },
                ),
                input_formats=[constants.HTML5_DATE_WIRE_FORMAT],
            )
            self.fields['exchange_date'].initial = bank_day
            self.initial['exchange_date'] = bank_day

        user_accounts = (
            self.account_repository.get_by_user(user)
            .filter(
                archived_at__isnull=True,
            )
            .exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)
        )
        accounts = list(user_accounts)
        initial_accounts = self._get_default_transfer_accounts(
            accounts,
            self.transfer_service.get_last_used_accounts(user),
        )
        from_account_initial = self.initial.get(
            'from_account',
            initial_accounts[0],
        )
        to_account_initial = self.initial.get(
            'to_account',
            initial_accounts[1],
        )
        if (
            from_account_initial is not None
            and from_account_initial == to_account_initial
        ):
            ordered_accounts = sorted(
                accounts,
                key=lambda account: (
                    account.created_at is not None,
                    account.created_at,
                ),
                reverse=True,
            )
            to_account_initial = self._get_latest_account(
                ordered_accounts,
                exclude_account=from_account_initial,
            )

        self.fields['from_account'] = ModelChoiceField(
            label=_('Со счёта:'),
            queryset=user_accounts,
            help_text=_('Выберите счёт, с которого будет списана сумма'),
            initial=from_account_initial,
        )

        self.fields['to_account'] = ModelChoiceField(
            label=_('На счёт:'),
            queryset=user_accounts,
            help_text=_('Выберите счёт, на который будет зачислена сумма'),
            initial=to_account_initial,
        )

        if self.initial.get('amount') is not None:
            self.fields['amount'].initial = self.initial['amount']
        if self.initial.get('exchange_date') is not None:
            self.fields['exchange_date'].initial = self.initial['exchange_date']

        self.add_tailwind_classes()

    def clean_exchange_date(self) -> datetime | None:
        """Anchor a known bank day to technical UTC midnight."""
        value = self.cleaned_data.get('exchange_date')
        if self.bank_day is not None:
            return datetime.combine(
                self.bank_day,
                time.min,
                tzinfo=UTC,
            )
        return value

    def _get_default_transfer_accounts(
        self,
        accounts: Sequence[Account],
        remembered_accounts: tuple[Account | None, Account | None],
    ) -> tuple[Account | None, Account | None]:
        """Return default source and destination accounts for transfer form."""
        if not accounts:
            return None, None

        accounts_by_id = {account.pk: account for account in accounts}
        remembered_from, remembered_to = remembered_accounts
        if (
            remembered_from is not None
            and remembered_to is not None
            and remembered_from.pk in accounts_by_id
            and remembered_to.pk in accounts_by_id
            and remembered_from.pk != remembered_to.pk
        ):
            return (
                accounts_by_id[remembered_from.pk],
                accounts_by_id[remembered_to.pk],
            )

        ordered_accounts = sorted(
            accounts,
            key=lambda account: (
                account.created_at is not None,
                account.created_at,
            ),
            reverse=True,
        )
        if len(ordered_accounts) == 1:
            return ordered_accounts[0], None

        from_account = self._get_latest_account_by_types(
            ordered_accounts,
            tuple(constants.LIQUID_ACCOUNT_TYPES),
        )
        if from_account is None:
            from_account = ordered_accounts[0]

        to_account = self._get_latest_account_by_types(
            ordered_accounts,
            tuple(constants.CREDIT_ACCOUNT_TYPES),
            exclude_account=from_account,
        )

        if to_account is None:
            to_account = self._get_latest_account(
                ordered_accounts,
                exclude_account=from_account,
            )

        return from_account, to_account

    def _get_latest_account_by_types(
        self,
        accounts: Sequence[Account],
        account_types: Sequence[str],
        exclude_account: Account | None = None,
    ) -> Account | None:
        """Return the latest created account matching the given types."""
        for account in accounts:
            if account == exclude_account:
                continue
            if account.type_account in account_types:
                return account
        return None

    def _get_latest_account(
        self,
        accounts: Sequence[Account],
        exclude_account: Account | None = None,
    ) -> Account | None:
        """Return the latest created account excluding one account if needed."""
        for account in accounts:
            if account != exclude_account:
                return account
        return None

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
        # The row is a hidden field: show its error above the form.
        for error in self.errors.pop('statement_row', []):
            self.add_error(None, error)

        if cleaned_data:
            from_account = cleaned_data.get('from_account')
            to_account = cleaned_data.get('to_account')
            amount = cleaned_data.get('amount')

            if from_account and to_account:
                try:
                    validate_different_accounts(from_account, to_account)
                except ValidationError as e:
                    self.add_error('to_account', e.message)

            if from_account and to_account:
                try:
                    validate_same_currency(from_account, to_account)
                except ValidationError as e:
                    self.add_error('to_account', e.message)

            if from_account and amount:
                try:
                    validate_account_balance(from_account, amount)
                except ValidationError as e:
                    self.add_error('from_account', e.message)

        return cleaned_data or {}

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


class BalanceAdjustmentForm(Form):
    """Asks for the actual account balance to align the account with."""

    actual_balance = DecimalField(
        label=_('Фактический остаток'),
        max_digits=constants.TWENTY,
        decimal_places=2,
        min_value=0,
    )


class BankStatementUploadForm(Form):
    """Form for uploading bank statements in PDF format."""

    pdf_file = FileField(
        label=_('PDF файл выписки'),
        widget=FileInput(attrs={'accept': '.pdf'}),
        help_text=_('Загрузите банковскую выписку в формате PDF'),
        error_messages={
            'required': _('Пожалуйста, выберите файл для загрузки.'),
        },
    )
    reconciliation_only = BooleanField(
        label=_('Только сверить'),
        required=False,
        help_text=_(
            'Сопоставить строки с учётом без создания новых операций. '
            'Каждую найденную операцию нужно подтвердить вручную.',
        ),
    )

    def __init__(self, user: User, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.fields['account'] = ModelChoiceField(
            queryset=(
                _account_manager.available_for_operations()
                .filter(user=user)
                .exclude(type_account=constants.ACCOUNT_TYPE_DEPOSIT)
            ),
            label=_('Счёт'),
            widget=Select(attrs={'class': 'statement-select'}),
            help_text=_('Выберите счёт, на который будут записаны операции'),
            error_messages={
                'required': _('Пожалуйста, выберите счёт.'),
            },
        )

    def clean_pdf_file(self) -> Any:
        """Validate PDF file."""
        pdf_file = self.cleaned_data.get('pdf_file')
        if pdf_file:
            if not pdf_file.name.endswith('.pdf'):
                raise ValidationError(
                    _('Разрешены только PDF файлы.'),
                )
            if pdf_file.size > 10 * 1024 * 1024:
                raise ValidationError(
                    _('Размер файла не должен превышать 10 МБ.'),
                )
            signature = pdf_file.read(len(constants.PDF_SIGNATURE))
            if signature != constants.PDF_SIGNATURE:
                raise ValidationError(
                    _('Файл не является корректным PDF.'),
                )
            pdf_file.seek(0)
        return pdf_file


class RepaymentTransferLinkForm(Form):
    """The transfer an owner picked to close a repayment row."""

    transfer = IntegerField(min_value=1)


class AccountCoverageForm(TailwindFormMixin, Form):
    """Explicit owner confirmation of inclusive account coverage dates."""

    account = ModelChoiceField(
        queryset=Account.objects.none(),
        label=_('Счёт'),
    )
    period_start = DateField(
        label=_('Начало периода'),
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=DateInput(
            format=constants.HTML5_DATE_INPUT_FORMAT,
            attrs={'type': 'date', 'lang': 'ru-RU'},
        ),
    )
    period_end = DateField(
        label=_('Конец периода'),
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        widget=DateInput(
            format=constants.HTML5_DATE_INPUT_FORMAT,
            attrs={'type': 'date', 'lang': 'ru-RU'},
        ),
    )
    source = ChoiceField(
        choices=AccountCoverageConfirmation.Source.choices,
        label=_('Источник покрытия'),
    )
    statement_upload = ModelChoiceField(
        queryset=BankStatementUpload.objects.none(),
        required=False,
        label=_('Выписка'),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.request_user: User | None = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.request_user is not None:
            account_field = cast(
                'ModelChoiceField[Account]',
                self.fields['account'],
            )
            account_field.queryset = Account.objects.filter(
                user=self.request_user,
            ).order_by('name_account')
            upload_field = cast(
                'ModelChoiceField[BankStatementUpload]',
                self.fields['statement_upload'],
            )
            upload_field.queryset = BankStatementUpload.objects.filter(
                user=self.request_user,
                account__user=self.request_user,
            ).order_by('-created_at')
        self.add_tailwind_classes()

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        if cleaned_data:
            start = cleaned_data.get('period_start')
            end = cleaned_data.get('period_end')
            if start is not None and end is not None and start > end:
                self.add_error(
                    'period_start',
                    _('Начало периода не может быть позже конца'),
                )
            source = cleaned_data.get('source')
            upload = cleaned_data.get('statement_upload')
            account = cleaned_data.get('account')
            if (
                source == AccountCoverageConfirmation.Source.MANUAL
                and upload is not None
            ):
                self.add_error(
                    'statement_upload',
                    _('Ручное покрытие не ссылается на выписку'),
                )
            if (
                upload is not None
                and account is not None
                and upload.account_id != account.pk
            ):
                self.add_error(
                    'statement_upload',
                    _('Выписка относится к другому счёту'),
                )
        return cleaned_data or {}


class StatementRowExcludeForm(Form):
    """The owner's reason for consciously leaving a statement row out."""

    reason = CharField(
        label=_('Причина исключения'),
        strip=True,
        widget=Textarea(attrs={'rows': 2}),
    )


def parse_balance_moment(
    raw_value: str,
    zone_name: str,
) -> datetime | None:
    """Parse an optional explicit balance instant without guessing a zone."""
    if not raw_value:
        return None
    moment = parse_datetime(raw_value)
    if moment is None:
        raise ValidationError(_('Не удалось разобрать момент остатка.'))
    if timezone.is_naive(moment):
        if not zone_name:
            raise ValidationError(
                _('Для момента остатка укажите часовой пояс.'),
            )
        try:
            moment = moment.replace(tzinfo=ZoneInfo(zone_name))
        except (KeyError, ValueError) as error:
            raise ValidationError(
                _('Неизвестный часовой пояс остатка.'),
            ) from error
    return moment


class BankStatementBalanceActionForm(Form):
    """Validate one balance-verification action of the reconciliation page."""

    class Action(TextChoices):
        """Every action the reconciliation page may submit."""

        CONFIRM = 'confirm_balance', _('Подтвердить остаток')
        VERIFY = 'verify_balance', _('Проверить остаток')
        EXPLAIN = 'explain_mismatch', _('Объяснить расхождение')

    action = ChoiceField(
        choices=Action.choices,
        error_messages={'invalid_choice': _('Неизвестное действие проверки.')},
    )
    balance_kind = ChoiceField(
        choices=BankStatementUpload.BalanceKind.choices,
        required=False,
    )
    balance_date = DateField(
        required=False,
        input_formats=list(constants.HTML5_DATE_INPUT_FORMATS),
        error_messages={
            'invalid': _('Не удалось разобрать дату остатка.'),
        },
    )
    balance_at = CharField(required=False, strip=True)
    timezone_name = CharField(required=False, strip=True)
    reason = CharField(required=False, strip=True)

    def clean(self) -> dict[str, Any]:
        """Parse the optional moment only for the action that needs it."""
        cleaned_data = super().clean()
        if cleaned_data and cleaned_data.get('action') == self.Action.CONFIRM:
            cleaned_data['balance_at'] = parse_balance_moment(
                cleaned_data.get('balance_at', ''),
                cleaned_data.get('timezone_name', ''),
            )
        return cleaned_data or {}
