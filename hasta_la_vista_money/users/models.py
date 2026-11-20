"""Django models for user management.

This module contains models for users and user-related features,
including dashboard widgets and admin configurations.
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from django.contrib import admin
from django.contrib.auth.models import AbstractUser, Group
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db.models import (
    CASCADE,
    PROTECT,
    SET_NULL,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    FileField,
    ForeignKey,
    Index,
    IntegerField,
    JSONField,
    Model,
    PositiveIntegerField,
    PositiveSmallIntegerField,
    Q,
    TextChoices,
    TextField,
    UniqueConstraint,
)
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django_stubs_ext.db.models.manager import RelatedManager

    from hasta_la_vista_money.budget.models import DateList
    from hasta_la_vista_money.finance_account.models import Account
    from hasta_la_vista_money.loan.models import (
        Loan,
        PaymentMakeLoan,
        PaymentSchedule,
    )
    from hasta_la_vista_money.receipts.models import Receipt
    from hasta_la_vista_money.transactions.models import Category

from hasta_la_vista_money.constants import (
    DEFAULT_TIMEZONE_NAME,
    STATEMENT_RETENTION_DAYS,
)
from hasta_la_vista_money.core.upload_paths import bank_statement_upload_to

#: Largest value a PostgreSQL ``integer`` column can hold.
MAX_DATABASE_INTEGER: Final = 2_147_483_647


def bank_statement_expires_at() -> datetime:
    """Return the default reconciliation and retention deadline."""
    return timezone.now() + timedelta(days=STATEMENT_RETENTION_DAYS)


def validate_statement_retention_days(value: int) -> None:
    """Reject retention values the database or a calendar date cannot hold.

    There is no product maximum: 100 years is allowed while an integer
    outside the column range or a deadline past ``datetime.max`` is not.
    """
    if value > MAX_DATABASE_INTEGER:
        raise ValidationError(
            _('Слишком большое число дней хранения: колонка не вместит его.'),
        )
    try:
        timezone.now() + timedelta(days=value)
    except OverflowError as error:
        raise ValidationError(
            _('Дата удаления выходит за допустимый диапазон дат.'),
        ) from error


class User(AbstractUser):
    """Extended user model with theme support.

    Extends Django's AbstractUser to add theme preference
    for the user interface.

    Attributes:
        theme: User's preferred theme (default: 'auto').
    """

    if TYPE_CHECKING:
        id: int
        categories: RelatedManager[Category]
        budget_date_lists: RelatedManager[DateList]
        loan_users: RelatedManager[Loan]
        payment_make_loan_users: RelatedManager[PaymentMakeLoan]
        payment_schedule_users: RelatedManager[PaymentSchedule]
        receipt_users: RelatedManager[Receipt]
        finance_account_users: RelatedManager[Account]

    theme: CharField[Any, Any] = CharField(max_length=10, default='auto')
    timezone_name: CharField[Any, Any] = CharField(
        max_length=64,
        default=DEFAULT_TIMEZONE_NAME,
    )
    statement_retention_days: PositiveIntegerField[Any, Any] = (
        PositiveIntegerField(
            default=STATEMENT_RETENTION_DAYS,
            validators=[
                MinValueValidator(1),
                validate_statement_retention_days,
            ],
            verbose_name=_('Срок хранения банковских выписок, дней'),
        )
    )

    def __str__(self) -> str:
        """Return string representation of the user.

        Returns:
            str: The username.
        """
        return str(self.username)


class DashboardWidget(Model):
    """Model for storing user dashboard widget settings.

    Stores configuration for dashboard widgets including position,
    size, visibility, and custom configuration data.

    Attributes:
        user: Foreign key to the User who owns this widget.
        widget_type: Type identifier of the widget.
        position: Position order of the widget on the dashboard.
        width: Width of the widget in grid units.
        height: Height of the widget in pixels.
        config: JSON field for widget-specific configuration.
        is_visible: Whether the widget is currently visible.
        created_at: Timestamp when the widget was created.
        updated_at: Timestamp when the widget was last updated.
    """

    user = ForeignKey(User, on_delete=CASCADE, related_name='dashboard_widgets')
    widget_type = CharField(max_length=50)
    position = PositiveIntegerField(default=0)
    width = PositiveIntegerField(default=6)
    height = PositiveIntegerField(default=300)
    config = JSONField(default=dict)
    is_visible = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'created_at']
        verbose_name = _('Виджет дашборда')
        verbose_name_plural = _('Виджеты дашборда')

    def __str__(self) -> str:
        """Return string representation of the widget.

        Returns:
            str: Formatted string with username and widget type.
        """
        return f'{self.user.username} - {self.widget_type}'


class BankStatementUpload(Model):
    """Model for tracking bank statement upload and processing status.

    Attributes:
        user: Foreign key to the User who uploaded the statement.
        account: Foreign key to the Account associated with the statement.
        pdf_file: Path to the uploaded PDF file.
        status: Current processing status (pending, processing, completed,
            failed).
        progress: Progress percentage (0-100).
        total_transactions: Total number of transactions found.
        processed_transactions: Number of transactions processed so far.
        income_count: Number of income transactions created.
        expense_count: Number of expense transactions created.
        error_message: Error message if processing failed.
        celery_task_id: Celery task ID for tracking.
        created_at: Timestamp when the upload was created.
        updated_at: Timestamp when the upload was last updated.
    """

    if TYPE_CHECKING:
        id: int
        user_id: int
        account_id: int
        balance_explained_by_id: int | None
        statement_rows: RelatedManager['BankStatementRow']

    class Status(TextChoices):
        PENDING = 'pending', _('В очереди')
        PROCESSING = 'processing', _('Обрабатывается')
        AWAITING_CONFIRMATION = (
            'awaiting_confirmation',
            _('Ожидает подтверждения'),
        )
        COMPLETED = 'completed', _('Завершено')
        COMPLETED_WITH_UNRESOLVED = (
            'completed_with_unresolved',
            _('Завершено с нерешёнными строками'),
        )
        FAILED = 'failed', _('Ошибка')

    class BalanceKind(TextChoices):
        """Meaning of the bank balance snapshot on the upload."""

        UNKNOWN = 'unknown', _('Семантика остатка неизвестна')
        OPENING = 'opening', _('Входящий остаток')
        CLOSING = 'closing', _('Исходящий остаток')
        AVAILABLE = 'available', _('Доступный остаток')

    class BalanceVerificationStatus(TextChoices):
        """Last conclusive historical balance comparison."""

        UNKNOWN = 'unknown', _('Не проверен')
        VERIFIED = 'verified', _('Совпадает')
        MISMATCH = 'mismatch', _('Расхождение')

    user = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='bank_statement_uploads',
    )
    account = ForeignKey('finance_account.Account', on_delete=CASCADE)
    pdf_file = FileField(upload_to=bank_statement_upload_to)
    file_hash = CharField(max_length=64, blank=True, default='')
    source_bank_code = CharField(max_length=50, blank=True, default='')
    status = CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING,
    )
    progress = IntegerField(default=0)
    total_transactions = IntegerField(default=0)
    processed_transactions = IntegerField(default=0)
    income_count = IntegerField(default=0)
    expense_count = IntegerField(default=0)
    skipped_count = IntegerField(default=0)
    imported_count = IntegerField(default=0)
    linked_count = IntegerField(default=0)
    awaiting_decision_count = IntegerField(default=0)
    needs_transfer_count = IntegerField(default=0)
    expired_count = IntegerField(default=0)
    failed_count = IntegerField(default=0)
    statement_closing_balance = DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_('Остаток по выписке'),
    )
    account_balance_after = DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_('Остаток в приложении после импорта'),
    )
    balance_discrepancy = DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_('Расхождение баланса'),
    )
    error_message = TextField(blank=True, default='')
    celery_task_id = CharField(max_length=255, blank=True, default='')
    expires_at = DateTimeField(default=bank_statement_expires_at)
    retention_cleaned_at = DateTimeField(blank=True, null=True)
    # Reconciliation-only import: no movement is posted automatically.
    reconciliation_only = BooleanField(default=False)
    # Version of the row traceability proofs this upload was processed with.
    processing_traceability_version = PositiveSmallIntegerField(default=0)
    # When row-by-row processing was proven, not when the file arrived.
    processing_verified_at = DateTimeField(blank=True, null=True)
    # Statement period taken from the document or confirmed by the user.
    statement_period_start = DateField(blank=True, null=True)
    statement_period_end = DateField(blank=True, null=True)
    # Verified historical bank balance. The moment and kind are only known
    # when the document or the owner supplies them; nothing is inferred.
    statement_balance_date = DateField(blank=True, null=True)
    statement_balance_at = DateTimeField(blank=True, null=True)
    statement_balance_kind = CharField(
        max_length=20,
        choices=BalanceKind.choices,
        default=BalanceKind.UNKNOWN,
    )
    statement_balance_timezone = CharField(
        max_length=64,
        blank=True,
        default='',
    )
    balance_verification_status = CharField(
        max_length=20,
        choices=BalanceVerificationStatus.choices,
        default=BalanceVerificationStatus.UNKNOWN,
    )
    balance_verified_at = DateTimeField(blank=True, null=True)
    balance_needs_recheck = BooleanField(default=False)
    balance_stale_reason = TextField(blank=True, default='')
    balance_unexplained_mismatch = BooleanField(default=False)
    balance_explained_by = ForeignKey(
        User,
        on_delete=SET_NULL,
        related_name='explained_statement_balance_checks',
        blank=True,
        null=True,
    )
    balance_explained_at = DateTimeField(blank=True, null=True)
    balance_explanation = TextField(blank=True, default='')
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Загрузка банковской выписки')
        verbose_name_plural = _('Загрузки банковских выписок')
        constraints = [
            UniqueConstraint(
                fields=['account', 'file_hash'],
                condition=~Q(file_hash=''),
                name='uniq_statement_account_file_hash',
            ),
        ]

    def __str__(self) -> str:
        """Return string representation of the upload.

        Returns:
            str: Formatted string with username and status.
        """
        return f'{self.user.username} - {self.status} - {self.created_at}'


class BankStatementRow(Model):
    """Parsed statement row awaiting a reconciliation decision."""

    if TYPE_CHECKING:
        upload_id: int
        candidate_id: int | None
        duplicate_of_id: int | None
        transaction_id: int | None
        transfer_id: int | None
        actor_id: int | None
        decision_audits: RelatedManager['BankStatementDecisionAudit']
        candidates: RelatedManager['BankStatementCandidate']

        def get_decision_display(self) -> str: ...

    class Decision(TextChoices):
        PENDING = 'pending', _('Ожидает решения')
        LINKED = 'linked', _('Уже учтена')
        NEW = 'new', _('Новая операция')
        NEEDS_TRANSFER = 'needs_transfer', _('Нужен перевод')
        TRANSFERRED = 'transferred', _('Уже учтена')
        NOT_A_PAYMENT = 'not_a_payment', _('Не погашение')
        EXPIRED = 'expired', _('Срок решения истёк')
        AWAITING_MARKUP = 'awaiting_markup', _('Ждёт разметки')
        MUTUAL_CANCEL = 'mutual_cancel', _('Взаимная отмена')
        # Legacy value: never written, migrated to DEFERRED.
        SKIPPED = 'skipped', _('Пропущена')
        DEFERRED = 'deferred', _('Отложена')
        EXCLUDED = 'excluded', _('Исключена')
        PARSE_ERROR = 'parse_error', _('Ошибка разбора')

    class ResumeDecision(TextChoices):
        """Mechanism a suspended row returns to when resumed."""

        AWAITING_MARKUP = 'awaiting_markup', _('Ждёт разметки')
        PENDING = 'pending', _('Ожидает решения')
        NEEDS_TRANSFER = 'needs_transfer', _('Нужен перевод')
        PARSE_ERROR = 'parse_error', _('Ошибка разбора')

    class DatePrecision(TextChoices):
        """How precisely the bank date of the row is known."""

        UNKNOWN = 'unknown', _('Дата неизвестна')
        DAY = 'day', _('Банковский день')
        DATETIME = 'datetime', _('Дата и время')

    class ParseError(TextChoices):
        """Fixed machine reasons why a potential operation was not parsed."""

        MISSING_DATE = 'missing_date', _('Не удалось определить дату')
        MISSING_NUMBER = 'missing_number', _('Не удалось определить номер')
        MISSING_AMOUNT = 'missing_amount', _('Не удалось определить сумму')
        MISSING_DIRECTION = (
            'missing_direction',
            _('Не удалось определить направление'),
        )
        MISSING_OPERATION = (
            'missing_operation',
            _('Не удалось разобрать операцию'),
        )

    class TransactionType(TextChoices):
        INCOME = 'income', _('Доход')
        EXPENSE = 'expense', _('Расход')

    upload = ForeignKey(
        BankStatementUpload,
        on_delete=CASCADE,
        related_name='statement_rows',
    )
    transaction_type = CharField(
        max_length=10,
        choices=TransactionType.choices,
        blank=True,
        null=True,
    )
    transaction_date = DateTimeField(blank=True, null=True)
    bank_calendar_date = DateField(blank=True, null=True)
    amount = DecimalField(
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
    )
    date_precision = CharField(
        max_length=10,
        choices=DatePrecision.choices,
        default=DatePrecision.UNKNOWN,
    )
    parse_error_code = CharField(
        max_length=20,
        choices=ParseError.choices,
        blank=True,
        default='',
    )
    description = CharField(max_length=250, blank=True, default='')
    candidate_description = CharField(max_length=250, blank=True, default='')
    suggested_category = CharField(max_length=250, blank=True, default='')
    source_ref = CharField(max_length=64, blank=True, null=True)
    source_ref_hash = CharField(max_length=64, blank=True, null=True)
    source_ref_key_id = CharField(max_length=64, blank=True, default='')
    source_ref_version = PositiveSmallIntegerField(default=1)
    source_identity_trusted = BooleanField(default=False)
    source_row_position = PositiveIntegerField(blank=True, null=True)
    data_expires_at = DateTimeField(blank=True, null=True)
    data_cleaned_at = DateTimeField(blank=True, null=True)
    match_calendar_date = BooleanField(default=False)
    # RosDorBankRowKind of a row awaiting markup.
    kind = CharField(max_length=10, blank=True, default='')
    merchant_key = CharField(max_length=250, blank=True, default='')
    counterparty_account = CharField(max_length=20, blank=True, default='')
    candidate = ForeignKey(
        'transactions.Transaction',
        on_delete=SET_NULL,
        related_name='statement_candidates',
        blank=True,
        null=True,
    )
    duplicate_of = ForeignKey(
        'self',
        on_delete=PROTECT,
        related_name='duplicate_presentations',
        blank=True,
        null=True,
    )
    transaction = ForeignKey(
        'transactions.Transaction',
        on_delete=SET_NULL,
        related_name='statement_rows',
        blank=True,
        null=True,
    )
    transfer = ForeignKey(
        'finance_account.TransferMoneyLog',
        on_delete=SET_NULL,
        related_name='statement_rows',
        blank=True,
        null=True,
    )
    decision = CharField(
        max_length=20,
        choices=Decision.choices,
        default=Decision.PENDING,
    )
    decision_reason = TextField(blank=True, default='')
    resume_decision = CharField(
        max_length=20,
        choices=ResumeDecision.choices,
        blank=True,
        default='',
    )
    created_at = DateTimeField(auto_now_add=True)
    decided_at = DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ['transaction_date', 'pk']
        constraints = [
            UniqueConstraint(
                fields=['upload', 'source_row_position'],
                name='unique_statement_upload_row',
            ),
            UniqueConstraint(
                fields=['transfer', 'transaction_type'],
                condition=Q(transfer__isnull=False),
                name='unique_statement_row_transfer',
            ),
        ]
        indexes = [
            Index(
                fields=['upload', 'decision'],
                name='users_statement_decision_idx',
            ),
        ]


class BankStatementCandidate(Model):
    """Financial movement matching a statement row."""

    row = ForeignKey(
        BankStatementRow,
        on_delete=CASCADE,
        related_name='candidates',
    )
    transaction = ForeignKey(
        'transactions.Transaction',
        on_delete=SET_NULL,
        related_name='statement_candidate_links',
        blank=True,
        null=True,
    )
    transfer = ForeignKey(
        'finance_account.TransferMoneyLog',
        on_delete=SET_NULL,
        related_name='statement_candidate_links',
        blank=True,
        null=True,
    )
    description = CharField(max_length=250)
    rank = PositiveIntegerField(default=0)

    class Meta:
        ordering = ['rank', 'pk']
        constraints = [
            UniqueConstraint(
                fields=['row', 'transaction'],
                name='unique_statement_row_candidate',
            ),
            UniqueConstraint(
                fields=['row', 'transfer'],
                condition=Q(transfer__isnull=False),
                name='unique_statement_row_transfer_candidate',
            ),
        ]


class MerchantCategory(Model):
    """Category the user last chose for a statement merchant key."""

    if TYPE_CHECKING:
        user_id: int
        category_id: int

    user = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='merchant_categories',
    )
    merchant_key = CharField(max_length=250)
    transaction_type = CharField(
        max_length=10,
        choices=BankStatementRow.TransactionType.choices,
    )
    category = ForeignKey(
        'transactions.Category',
        on_delete=CASCADE,
        related_name='merchant_categories',
    )

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=['user', 'merchant_key', 'transaction_type'],
                name='unique_merchant_category',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.merchant_key} -> {self.category_id}'


class BankStatementDecisionAudit(Model):
    """Immutable audit entry for a statement reconciliation decision."""

    row = ForeignKey(
        BankStatementRow,
        on_delete=CASCADE,
        related_name='decision_audits',
    )
    actor = ForeignKey(
        User,
        on_delete=SET_NULL,
        related_name='statement_decision_audits',
        blank=True,
        null=True,
    )

    if TYPE_CHECKING:
        actor_id: int | None
    decision = CharField(
        max_length=20,
        choices=BankStatementRow.Decision.choices,
    )
    previous_transaction = ForeignKey(
        'transactions.Transaction',
        on_delete=SET_NULL,
        related_name='previous_statement_decision_audits',
        blank=True,
        null=True,
    )
    previous_transfer = ForeignKey(
        'finance_account.TransferMoneyLog',
        on_delete=SET_NULL,
        related_name='previous_statement_decision_audits',
        blank=True,
        null=True,
    )
    transaction = ForeignKey(
        'transactions.Transaction',
        on_delete=SET_NULL,
        related_name='statement_decision_audits',
        blank=True,
        null=True,
    )
    transfer = ForeignKey(
        'finance_account.TransferMoneyLog',
        on_delete=SET_NULL,
        related_name='statement_decision_audits',
        blank=True,
        null=True,
    )
    reason = TextField(blank=True, default='')
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']


class FamilyGroupMembership(Model):
    """User role inside a shared family finance group."""

    if TYPE_CHECKING:
        group_id: int
        user_id: int

    class Role(TextChoices):
        OWNER = 'owner', _('Владелец')
        VIEWER = 'viewer', _('Просмотр')

    group = ForeignKey(
        Group,
        on_delete=CASCADE,
        related_name='family_memberships',
    )
    user = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='family_memberships',
    )
    role = CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
    )
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=['group', 'user'],
                name='unique_family_group_membership',
            ),
        ]
        verbose_name = _('Участник семейной группы')
        verbose_name_plural = _('Участники семейных групп')

    def __str__(self) -> str:
        return f'{self.group.name}: {self.user.username} ({self.role})'


class FamilyInvite(Model):
    """Share link for joining a family finance group."""

    group = ForeignKey(
        Group,
        on_delete=CASCADE,
        related_name='family_invites',
    )
    created_by = ForeignKey(
        User,
        on_delete=CASCADE,
        related_name='created_family_invites',
    )
    token = CharField(max_length=64, unique=True)
    role = CharField(
        max_length=20,
        choices=FamilyGroupMembership.Role.choices,
        default=FamilyGroupMembership.Role.VIEWER,
    )
    is_active = BooleanField(default=True)
    expires_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Семейное приглашение')
        verbose_name_plural = _('Семейные приглашения')

    def __str__(self) -> str:
        return f'{self.group.name}: {self.role}'


class TokenAdmin(admin.ModelAdmin[Any]):
    """Admin configuration for token model.

    Provides search functionality for tokens by key and username.
    """

    search_fields = ('key', 'user__username')
