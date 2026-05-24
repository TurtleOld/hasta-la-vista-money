"""Validation for parsed receipt payloads from receipt-inference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final


class ReceiptParseValidationError(ValueError):
    """Raised when receipt-inference returns an invalid receipt payload.

    ``user_message`` carries an end-user-facing explanation in Russian for the
    pending-receipt card. When omitted, callers fall back to a generic message.
    """

    def __init__(self, message: str, *, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message


_USER_MSG_TOTAL_MISMATCH = (
    'Сумма позиций не совпадает с итогом чека. '
    'Скорее всего, несколько позиций не распознались — '
    'попробуйте загрузить более чёткое фото.'
)
_USER_MSG_NO_ITEMS = (
    'Не удалось распознать ни одной позиции на чеке. '
    'Попробуйте загрузить более чёткое фото.'
)
_USER_MSG_BAD_TOTAL = (
    'Не удалось распознать итоговую сумму чека. '
    'Попробуйте загрузить более чёткое фото.'
)
_USER_MSG_BAD_DATE = (
    'Не удалось распознать дату чека. Попробуйте загрузить более чёткое фото.'
)
_USER_MSG_BAD_SELLER = (
    'Не удалось распознать продавца. Попробуйте загрузить более чёткое фото.'
)
_USER_MSG_BAD_ITEM = (
    'Одна из позиций чека распозналась некорректно. '
    'Попробуйте загрузить более чёткое фото.'
)
_USER_MSG_BAD_STRUCTURE = (
    'Сервис распознавания вернул чек в неожиданном формате. '
    'Попробуйте загрузить чек ещё раз.'
)


TOP_LEVEL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        'name_seller',
        'retail_place_address',
        'retail_place',
        'total_sum',
        'operation_type',
        'receipt_date',
        'number_receipt',
        'nds10',
        'nds20',
        'items',
    },
)
REQUIRED_TOP_LEVEL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        'name_seller',
        'total_sum',
        'operation_type',
        'receipt_date',
        'items',
    },
)
ITEM_FIELDS: Final[frozenset[str]] = frozenset(
    {'product_name', 'category', 'price', 'quantity', 'amount'},
)
REQUIRED_ITEM_FIELDS: Final[frozenset[str]] = frozenset(
    {'product_name', 'price', 'quantity', 'amount'},
)
ALLOWED_OPERATION_TYPES: Final[frozenset[int]] = frozenset({1, 2, 3, 4})
TOTAL_SUM_TOLERANCE_RATIO: Final[Decimal] = Decimal('0.02')
TOTAL_SUM_TOLERANCE_MIN: Final[Decimal] = Decimal('1.00')

RECEIPT_PARSE_SCHEMA: Final[dict[str, Any]] = {
    'type': 'object',
    'additionalProperties': False,
    'required': sorted(REQUIRED_TOP_LEVEL_FIELDS),
    'properties': {
        'name_seller': {'type': 'string', 'minLength': 1},
        'retail_place_address': {'type': ['string', 'null']},
        'retail_place': {'type': ['string', 'null']},
        'total_sum': {'type': ['number', 'string'], 'exclusiveMinimum': 0},
        'operation_type': {'type': ['integer', 'string'], 'enum': [1, 2, 3, 4]},
        'receipt_date': {
            'type': 'string',
            'description': 'DD.MM.YYYY HH:MM or short-year equivalent',
        },
        'number_receipt': {'type': ['integer', 'string', 'null']},
        'nds10': {'type': ['number', 'string', 'null'], 'minimum': 0},
        'nds20': {'type': ['number', 'string', 'null'], 'minimum': 0},
        'items': {
            'type': 'array',
            'minItems': 1,
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': sorted(REQUIRED_ITEM_FIELDS),
                'properties': {
                    'product_name': {'type': 'string', 'minLength': 1},
                    'category': {'type': 'string'},
                    'price': {'type': ['number', 'string'], 'minimum': 0},
                    'quantity': {
                        'type': ['number', 'string'],
                        'exclusiveMinimum': 0,
                    },
                    'amount': {'type': ['number', 'string'], 'minimum': 0},
                },
            },
        },
    },
}


@dataclass(frozen=True)
class ReceiptParseItem:
    """Normalized receipt line item accepted by the review flow."""

    product_name: str
    category: str
    price: Decimal
    quantity: Decimal
    amount: Decimal

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable item data."""
        return {
            'product_name': self.product_name,
            'category': self.category,
            'price': _format_decimal(self.price),
            'quantity': _format_decimal(self.quantity),
            'amount': _format_decimal(self.amount),
        }


@dataclass(frozen=True)
class ReceiptParseResult:
    """Normalized receipt payload accepted by PendingReceiptService."""

    name_seller: str
    total_sum: Decimal
    operation_type: int
    receipt_date: str
    items: tuple[ReceiptParseItem, ...]
    retail_place_address: str | None = None
    retail_place: str | None = None
    number_receipt: int | None = None
    nds10: Decimal | None = None
    nds20: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable receipt data for JSONField storage."""
        return {
            'name_seller': self.name_seller,
            'retail_place_address': self.retail_place_address,
            'retail_place': self.retail_place,
            'total_sum': _format_decimal(self.total_sum),
            'operation_type': self.operation_type,
            'receipt_date': self.receipt_date,
            'number_receipt': self.number_receipt,
            'nds10': _format_optional_decimal(self.nds10),
            'nds20': _format_optional_decimal(self.nds20),
            'items': [item.to_dict() for item in self.items],
        }


def validate_receipt_parse_payload(
    payload: dict[str, Any],
) -> ReceiptParseResult:
    """Validate and normalize receipt-inference payload.

    The local inference service already normalizes most values, but this
    pre-flight validation is the Django-side contract before ``mark_ready``.
    """
    _validate_object_keys(payload, TOP_LEVEL_FIELDS, 'receipt')
    _validate_required_fields(payload, REQUIRED_TOP_LEVEL_FIELDS, 'receipt')

    items_raw = payload.get('items')
    if not isinstance(items_raw, list) or not items_raw:
        raise ReceiptParseValidationError(
            'receipt.items must be a non-empty list',
            user_message=_USER_MSG_NO_ITEMS,
        )

    items = tuple(
        _validate_item(item, index=index)
        for index, item in enumerate(items_raw, start=1)
    )
    total_sum = _parse_decimal(
        payload.get('total_sum'),
        'receipt.total_sum',
        user_message=_USER_MSG_BAD_TOTAL,
    )
    if total_sum <= 0:
        raise ReceiptParseValidationError(
            'receipt.total_sum must be positive',
            user_message=_USER_MSG_BAD_TOTAL,
        )

    _validate_items_total(total_sum, items)

    operation_type = _parse_int(
        payload.get('operation_type'),
        'receipt.operation_type',
    )
    if operation_type not in ALLOWED_OPERATION_TYPES:
        raise ReceiptParseValidationError(
            'receipt.operation_type must be one of 1, 2, 3, 4',
            user_message=_USER_MSG_BAD_STRUCTURE,
        )

    receipt_date = _parse_receipt_date(payload.get('receipt_date'))
    return ReceiptParseResult(
        name_seller=_parse_required_text(
            payload.get('name_seller'),
            'receipt.name_seller',
            user_message=_USER_MSG_BAD_SELLER,
        ),
        retail_place_address=_parse_optional_text(
            payload.get('retail_place_address'),
        ),
        retail_place=_parse_optional_text(payload.get('retail_place')),
        total_sum=total_sum,
        operation_type=operation_type,
        receipt_date=receipt_date,
        number_receipt=_parse_optional_int(
            payload.get('number_receipt'),
            'receipt.number_receipt',
        ),
        nds10=_parse_optional_non_negative_decimal(
            payload.get('nds10'),
            'receipt.nds10',
        ),
        nds20=_parse_optional_non_negative_decimal(
            payload.get('nds20'),
            'receipt.nds20',
        ),
        items=items,
    )


def _validate_item(value: Any, *, index: int) -> ReceiptParseItem:
    if not isinstance(value, dict):
        message = f'receipt.items[{index}] must be an object'
        raise ReceiptParseValidationError(
            message,
            user_message=_USER_MSG_BAD_ITEM,
        )
    path = f'receipt.items[{index}]'
    _validate_object_keys(value, ITEM_FIELDS, path)
    _validate_required_fields(value, REQUIRED_ITEM_FIELDS, path)

    price = _parse_decimal(
        value.get('price'),
        f'{path}.price',
        user_message=_USER_MSG_BAD_ITEM,
    )
    quantity = _parse_decimal(
        value.get('quantity'),
        f'{path}.quantity',
        user_message=_USER_MSG_BAD_ITEM,
    )
    amount = _parse_decimal(
        value.get('amount'),
        f'{path}.amount',
        user_message=_USER_MSG_BAD_ITEM,
    )
    if price < 0:
        message = f'{path}.price must not be negative'
        raise ReceiptParseValidationError(
            message,
            user_message=_USER_MSG_BAD_ITEM,
        )
    if quantity <= 0:
        message = f'{path}.quantity must be positive'
        raise ReceiptParseValidationError(
            message,
            user_message=_USER_MSG_BAD_ITEM,
        )
    if amount < 0:
        message = f'{path}.amount must not be negative'
        raise ReceiptParseValidationError(
            message,
            user_message=_USER_MSG_BAD_ITEM,
        )

    return ReceiptParseItem(
        product_name=_parse_required_text(
            value.get('product_name'),
            f'{path}.product_name',
            user_message=_USER_MSG_BAD_ITEM,
        ),
        category=_parse_optional_text(value.get('category')) or 'Прочее',
        price=price,
        quantity=quantity,
        amount=amount,
    )


def _validate_items_total(
    total_sum: Decimal,
    items: tuple[ReceiptParseItem, ...],
) -> None:
    items_total = sum((item.amount for item in items), Decimal(0))
    if items_total <= 0:
        raise ReceiptParseValidationError(
            'receipt.items total must be positive',
            user_message=_USER_MSG_TOTAL_MISMATCH,
        )

    allowed_diff = max(
        total_sum * TOTAL_SUM_TOLERANCE_RATIO,
        TOTAL_SUM_TOLERANCE_MIN,
    )
    if abs(total_sum - items_total) > allowed_diff:
        raise ReceiptParseValidationError(
            'receipt.total_sum differs from receipt.items total by more '
            'than 2%',
            user_message=_USER_MSG_TOTAL_MISMATCH,
        )


def _validate_object_keys(
    payload: dict[str, Any],
    allowed_keys: frozenset[str],
    path: str,
) -> None:
    unknown_keys = sorted(set(payload) - allowed_keys)
    if unknown_keys:
        message = f'{path} contains unknown fields: {", ".join(unknown_keys)}'
        raise ReceiptParseValidationError(
            message,
            user_message=_USER_MSG_BAD_STRUCTURE,
        )


def _validate_required_fields(
    payload: dict[str, Any],
    required_keys: frozenset[str],
    path: str,
) -> None:
    missing_keys = sorted(key for key in required_keys if key not in payload)
    if missing_keys:
        message = (
            f'{path} is missing required fields: {", ".join(missing_keys)}'
        )
        raise ReceiptParseValidationError(
            message,
            user_message=_USER_MSG_BAD_STRUCTURE,
        )


def _parse_decimal(
    value: Any,
    path: str,
    *,
    user_message: str | None = None,
) -> Decimal:
    if isinstance(value, bool) or value is None:
        message = f'{path} must be a number'
        raise ReceiptParseValidationError(message, user_message=user_message)
    try:
        decimal_value = Decimal(str(value).replace(',', '.').replace(' ', ''))
    except (InvalidOperation, ValueError) as exc:
        message = f'{path} must be a number'
        raise ReceiptParseValidationError(
            message,
            user_message=user_message,
        ) from exc
    if not decimal_value.is_finite():
        message = f'{path} must be a finite number'
        raise ReceiptParseValidationError(message, user_message=user_message)
    return decimal_value


def _parse_optional_non_negative_decimal(
    value: Any,
    path: str,
) -> Decimal | None:
    if value is None or value == '':
        return None
    decimal_value = _parse_decimal(value, path)
    if decimal_value < 0:
        message = f'{path} must not be negative'
        raise ReceiptParseValidationError(
            message,
            user_message=_USER_MSG_BAD_STRUCTURE,
        )
    return decimal_value


def _parse_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or value is None:
        message = f'{path} must be an integer'
        raise ReceiptParseValidationError(
            message,
            user_message=_USER_MSG_BAD_STRUCTURE,
        )
    try:
        return int(str(value).strip())
    except ValueError as exc:
        message = f'{path} must be an integer'
        raise ReceiptParseValidationError(
            message,
            user_message=_USER_MSG_BAD_STRUCTURE,
        ) from exc


def _parse_optional_int(value: Any, path: str) -> int | None:
    if value is None or value == '':
        return None
    return _parse_int(value, path)


def _parse_required_text(
    value: Any,
    path: str,
    *,
    user_message: str | None = None,
) -> str:
    text = _parse_optional_text(value)
    if text is None:
        message = f'{path} must be a non-empty string'
        raise ReceiptParseValidationError(message, user_message=user_message)
    return text


def _parse_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_receipt_date(value: Any) -> str:
    text = _parse_required_text(
        value,
        'receipt.receipt_date',
        user_message=_USER_MSG_BAD_DATE,
    )
    for date_format in ('%d.%m.%Y %H:%M', '%d.%m.%y %H:%M'):
        try:
            parsed = datetime.strptime(text, date_format).replace(tzinfo=UTC)
        except ValueError:
            continue
        return parsed.strftime('%d.%m.%Y %H:%M')
    raise ReceiptParseValidationError(
        'receipt.receipt_date must be parseable as DD.MM.YYYY HH:MM',
        user_message=_USER_MSG_BAD_DATE,
    )


def _format_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal('0.01')), 'f')


def _format_optional_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _format_decimal(value)


__all__ = [
    'RECEIPT_PARSE_SCHEMA',
    'ReceiptParseResult',
    'ReceiptParseValidationError',
    'validate_receipt_parse_payload',
]
