"""Map FNS receipt JSON to the current pending receipt payload contract."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone

_KOPECKS = Decimal(100)


class FNSReceiptMappingError(ValueError):
    """Raised when FNS JSON cannot be mapped to receipt_data."""


def map_fns_receipt_to_receipt_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Map an FNS ticket/receipt response to existing receipt_data fields."""
    receipt = _extract_receipt(payload)
    retail_place = _optional_text(receipt.get('retailPlace'))
    legal_name = _legal_name(receipt)
    seller_name = retail_place or legal_name or 'Неизвестный продавец'

    return {
        'name_seller': seller_name,
        'retail_place_address': _optional_text(
            receipt.get('retailPlaceAddress'),
        ),
        'retail_place': retail_place,
        'inn': _optional_text(receipt.get('userInn')),
        'total_sum': _format_money(receipt.get('totalSum')),
        'operation_type': _parse_int(receipt.get('operationType'), default=1),
        'receipt_date': _format_receipt_date(receipt.get('dateTime')),
        'number_receipt': _parse_optional_int(
            receipt.get('fiscalDocumentNumber'),
        ),
        'nds10': _format_optional_money(receipt.get('nds10')),
        'nds20': _format_optional_money(receipt.get('nds20')),
        'items': [_map_item(item) for item in _extract_items(receipt)],
    }


def _extract_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    receipt = _as_dict(payload.get('receipt'))
    if receipt is not None:
        return receipt

    document = payload.get('document')
    if isinstance(document, dict):
        receipt = _as_dict(document.get('receipt'))
        if receipt is not None:
            return receipt

    ticket = payload.get('ticket')
    if isinstance(ticket, dict):
        document = ticket.get('document')
        if isinstance(document, dict):
            receipt = _as_dict(document.get('receipt'))
            if receipt is not None:
                return receipt

    raise FNSReceiptMappingError('FNS response has no receipt object')


def _extract_items(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    items = receipt.get('items')
    if not isinstance(items, list) or not items:
        raise FNSReceiptMappingError('FNS receipt has no items')
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise FNSReceiptMappingError('FNS receipt item is not an object')
        result.append(item)
    return result


def _map_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        'product_name': _required_text(item.get('name'), 'item.name'),
        'category': 'Прочее',
        'price': _format_money(item.get('price')),
        'quantity': _format_quantity(item.get('quantity')),
        'amount': _format_money(item.get('sum')),
    }


def _legal_name(receipt: dict[str, Any]) -> str | None:
    name = _optional_text(receipt.get('user'))
    if name:
        return name
    organization = receipt.get('organization')
    if isinstance(organization, dict):
        return _optional_text(organization.get('name'))
    return None


def _format_money(value: Any) -> str:
    if value is None or isinstance(value, bool):
        raise FNSReceiptMappingError('FNS money value is required')
    try:
        result = Decimal(str(value)) / _KOPECKS
    except (InvalidOperation, ValueError) as exc:
        raise FNSReceiptMappingError('FNS money value is invalid') from exc
    return format(result.quantize(Decimal('0.01')), 'f')


def _format_optional_money(value: Any) -> str | None:
    if value is None or value == '':
        return None
    return _format_money(value)


def _format_quantity(value: Any) -> str:
    if value is None or isinstance(value, bool):
        raise FNSReceiptMappingError('FNS item quantity is required')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FNSReceiptMappingError('FNS item quantity is invalid') from exc
    return format(result.normalize(), 'f')


def _format_receipt_date(value: Any) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        parsed = datetime.fromtimestamp(value, tz=UTC)
        return timezone.localtime(parsed).strftime('%d.%m.%Y %H:%M')

    text = _required_text(value, 'receipt.dateTime')
    normalized = text.replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for date_format in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                parsed = datetime.strptime(text, date_format).replace(
                    tzinfo=timezone.get_current_timezone(),
                )
            except ValueError:
                continue
            return parsed.strftime('%d.%m.%Y %H:%M')
        raise FNSReceiptMappingError('FNS receipt date is invalid') from None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.get_current_timezone())
    return timezone.localtime(parsed).strftime('%d.%m.%Y %H:%M')


def _parse_int(value: Any, *, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if value is None or isinstance(value, bool):
        raise FNSReceiptMappingError('FNS integer value is required')
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise FNSReceiptMappingError('FNS integer value is invalid') from exc


def _parse_optional_int(value: Any) -> int | None:
    if value is None or value == '':
        return None
    return _parse_int(value)


def _required_text(value: Any, path: str) -> str:
    text = _optional_text(value)
    if text is None:
        message = f'FNS text value is required: {path}'
        raise FNSReceiptMappingError(message)
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_dict(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


__all__ = ['FNSReceiptMappingError', 'map_fns_receipt_to_receipt_data']
