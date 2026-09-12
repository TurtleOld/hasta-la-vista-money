"""Registry of audited fields, applied when audit history is rendered.

Presence of a field in the registry means the field is a meaningful change
and is shown to the user; absence means it is hidden. Audit entries keep
every changed field regardless — hidden is not the same as unrecorded.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _


class Formatter(Enum):
    """Closed set of value formats supported by the registry."""

    MONEY = 'money'
    DATE = 'date'
    DATETIME = 'datetime'
    CHOICE = 'choice'
    FK = 'fk'
    TEXT = 'text'


class Related(Enum):
    """Referenced object whose name is printed instead of a raw id."""

    ACCOUNT = 'account'
    SELLER = 'seller'
    CATEGORY = 'category'
    BANK = 'bank'


class CurrencySource(Enum):
    """Where the currency of a money field is taken from."""

    SELF = 'self'
    ACCOUNT = 'account_id'
    FROM_ACCOUNT = 'from_account_id'


@dataclass(frozen=True)
class AuditField:
    """Human-facing description of one audited field."""

    label: str | Promise
    format: Formatter
    related: Related | None = None
    currency_from: CurrencySource | None = None
    choices: Mapping[Any, str | Promise] | None = None
    participant: bool = False


RECEIPT_OPERATION_TYPES: Final[Mapping[Any, str]] = MappingProxyType(
    {
        1: 'Приход',
        2: 'Возврат прихода',
        3: 'Расход',
        4: 'Возврат расхода',
    },
)

ACCOUNT_LABEL: Final = 'finance_account.Account'
TRANSACTION_LABEL: Final = 'transactions.Transaction'
RECEIPT_LABEL: Final = 'receipts.Receipt'
TRANSFER_LABEL: Final = 'finance_account.TransferMoneyLog'

# Declaration order is significant: it is the order fields are listed.
AUDIT_FIELDS: Final[Mapping[str, Mapping[str, AuditField]]] = MappingProxyType(
    {
        ACCOUNT_LABEL: MappingProxyType(
            {
                'name_account': AuditField(
                    _('Название счёта'),
                    Formatter.TEXT,
                    participant=True,
                ),
                'type_account': AuditField(_('Тип счёта'), Formatter.CHOICE),
                'bank_id': AuditField(
                    _('Банк'),
                    Formatter.FK,
                    related=Related.BANK,
                ),
                'balance': AuditField(
                    _('Остаток'),
                    Formatter.MONEY,
                    currency_from=CurrencySource.SELF,
                ),
                'currency': AuditField(_('Валюта'), Formatter.CHOICE),
                'limit_credit': AuditField(
                    _('Кредитный лимит'),
                    Formatter.MONEY,
                    currency_from=CurrencySource.SELF,
                ),
                'payment_due_date': AuditField(
                    _('Дата платежа'),
                    Formatter.DATE,
                ),
                'grace_period_days': AuditField(
                    _('Льготный период, дней'),
                    Formatter.TEXT,
                ),
                'archived_at': AuditField(
                    _('Дата архивации'),
                    Formatter.DATETIME,
                ),
                'last_reconciled_at': AuditField(
                    _('Дата последней сверки'),
                    Formatter.DATETIME,
                ),
            },
        ),
        TRANSACTION_LABEL: MappingProxyType(
            {
                'type': AuditField(_('Тип операции'), Formatter.CHOICE),
                'date': AuditField(_('Дата операции'), Formatter.DATETIME),
                'amount': AuditField(
                    _('Сумма'),
                    Formatter.MONEY,
                    currency_from=CurrencySource.ACCOUNT,
                ),
                'account_id': AuditField(
                    _('Счёт'),
                    Formatter.FK,
                    related=Related.ACCOUNT,
                    participant=True,
                ),
                'category_id': AuditField(
                    _('Категория'),
                    Formatter.FK,
                    related=Related.CATEGORY,
                ),
                'description': AuditField(_('Описание'), Formatter.TEXT),
            },
        ),
        RECEIPT_LABEL: MappingProxyType(
            {
                'receipt_date': AuditField(_('Дата чека'), Formatter.DATETIME),
                'total_sum': AuditField(
                    _('Сумма чека'),
                    Formatter.MONEY,
                    currency_from=CurrencySource.ACCOUNT,
                ),
                'seller_id': AuditField(
                    _('Продавец'),
                    Formatter.FK,
                    related=Related.SELLER,
                    participant=True,
                ),
                'account_id': AuditField(
                    _('Счёт'),
                    Formatter.FK,
                    related=Related.ACCOUNT,
                    participant=True,
                ),
                'operation_type': AuditField(
                    _('Тип операции'),
                    Formatter.CHOICE,
                    choices=RECEIPT_OPERATION_TYPES,
                ),
                'adjustment': AuditField(
                    _('Корректировка'),
                    Formatter.MONEY,
                    currency_from=CurrencySource.ACCOUNT,
                ),
            },
        ),
        TRANSFER_LABEL: MappingProxyType(
            {
                'from_account_id': AuditField(
                    _('Счёт списания'),
                    Formatter.FK,
                    related=Related.ACCOUNT,
                    participant=True,
                ),
                'to_account_id': AuditField(
                    _('Счёт зачисления'),
                    Formatter.FK,
                    related=Related.ACCOUNT,
                    participant=True,
                ),
                'amount': AuditField(
                    _('Сумма'),
                    Formatter.MONEY,
                    currency_from=CurrencySource.FROM_ACCOUNT,
                ),
                'exchange_date': AuditField(
                    _('Дата перевода'),
                    Formatter.DATETIME,
                ),
                'notes': AuditField(_('Примечание'), Formatter.TEXT),
            },
        ),
    },
)

# Explicit, not "everything else": the consistency test needs both halves
# to be named so a new model field fails the build instead of leaking raw.
HIDDEN_AUDIT_FIELDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        ACCOUNT_LABEL: frozenset(
            {
                'id',
                'user_id',
                'created_at',
                'updated_at',
            },
        ),
        TRANSACTION_LABEL: frozenset(
            {
                'id',
                'user_id',
                'created_at',
                'source_ref',
                'source_file_hash',
                'source_row_position',
            },
        ),
        RECEIPT_LABEL: frozenset(
            {
                'id',
                'user_id',
                'created_at',
                'number_receipt',
                'nds10',
                'nds20',
                'fiscal_key',
                'manual',
                'requires_attention',
                'attention_reason',
            },
        ),
        TRANSFER_LABEL: frozenset(
            {
                'id',
                'user_id',
                'created_at',
                'updated_at',
            },
        ),
    },
)


def get_audit_field(model_label: str, attname: str) -> AuditField | None:
    """Return the registry entry for a field, or None when it is hidden."""
    return AUDIT_FIELDS.get(model_label, {}).get(attname)
